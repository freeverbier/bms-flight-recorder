#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Exécutez ce script avec sudo." >&2
  exit 1
fi

if [[ $(dpkg --print-architecture) != "amd64" ]]; then
  echo "Cette version cible Debian x86_64/amd64." >&2
  exit 1
fi

source /etc/os-release
if [[ ${ID:-} != "debian" ]]; then
  echo "Système non Debian détecté (${PRETTY_NAME:-inconnu})." >&2
  exit 1
fi

CAPTURE_INTERFACE=${1:-ens192}
INSTALL_DIR=/opt/bms-flight-recorder
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

# Validate the delivery before installing packages or copying anything.
for required in docker-compose.yml .env.example ui/package.json ui/Dockerfile; do
  if [[ ! -s "$SOURCE_DIR/$required" ]]; then
    echo "Livraison incomplète : $SOURCE_DIR/$required absent ou vide. Réextraire l'archive complète." >&2
    exit 1
  fi
done

apt-get update
apt-get install -y ca-certificates curl openssl rsync
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

install -m 0750 -d "$INSTALL_DIR"
if [[ "$SOURCE_DIR" != "$(cd "$INSTALL_DIR" && pwd -P)" ]]; then
  rsync -a --exclude '.env' --exclude 'node_modules' --exclude 'dist' "$SOURCE_DIR/" "$INSTALL_DIR/"
fi
cd "$INSTALL_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s/^CAPTURE_INTERFACE=.*/CAPTURE_INTERFACE=${CAPTURE_INTERFACE}/" .env
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
  sed -i "s/^INFLUXDB_ADMIN_PASSWORD=.*/INFLUXDB_ADMIN_PASSWORD=$(openssl rand -hex 24)/" .env
  sed -i "s/^INFLUXDB_ADMIN_TOKEN=.*/INFLUXDB_ADMIN_TOKEN=$(openssl rand -hex 32)/" .env
  sed -i "s/^MINIO_ROOT_PASSWORD=.*/MINIO_ROOT_PASSWORD=$(openssl rand -hex 24)/" .env
  sed -i "s/^APP_MASTER_KEY=.*/APP_MASTER_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')/" .env
  sed -i "s/^INTERNAL_TOKEN=.*/INTERNAL_TOKEN=$(openssl rand -hex 32)/" .env
  chmod 0600 .env
fi

if ! grep -q '^CLICKHOUSE_PASSWORD=.' .env || grep -q '^CLICKHOUSE_PASSWORD=change-me$' .env; then
  sed -i '/^CLICKHOUSE_PASSWORD=/d' .env
  printf 'CLICKHOUSE_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> .env
fi

systemctl enable --now docker
docker compose config --quiet
docker compose build
docker compose up -d

echo
echo "BMS Flight Recorder est disponible sur http://$(hostname -I | awk '{print $1}'):${PUBLIC_PORT:-8080}"
echo "La capture privilégiée n'est pas activée par défaut."
echo "Après vérification du port miroir : cd $INSTALL_DIR && docker compose --profile capture up -d"
