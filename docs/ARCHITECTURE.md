# Architecture et interfaçage

## Flux principal

1. `api` enregistre les demandes de scan dans PostgreSQL et restitue les équipements découverts.
2. `protocol-collector` exécute les scans BACnet Who-Is et maintient les sources BACnet/Modbus.
3. `knx-collector` exécute les recherches KNXnet/IP, puis maintient les connexions routing et tunneling.
4. `capture`, optionnel, enregistre sur l'interface réseau de la VM les échanges auxquels elle participe ; `decoder` indexe alors les PCAPNG avec TShark dans ClickHouse et InfluxDB.
5. `proxy` expose un seul port HTTP et distribue `/api/*` vers l'API et le reste vers l'interface.

## Répartition des données

| Donnée | Stockage | Rétention initiale |
| --- | --- | --- |
| Fichiers PCAPNG | Volume Docker, puis MinIO | Nombre de fichiers configuré |
| Trames et métadonnées | ClickHouse `bms.frames` | 180 jours |
| Valeurs temporelles | InfluxDB `telemetry` | Politique du bucket |
| Sources, maps de points, gateways, profils | PostgreSQL | Permanente |
| Contenu secret | PostgreSQL, enveloppe Fernet | Permanente/rotation manuelle |

Les valeurs décodées sont écrites dans InfluxDB avec `protocol`, `point_id` et `sensor_id` comme tags. Les octets bruts, hashes et identifiants uniques de paquets restent hors des tags.

## BACnet/IP

Le port SPAN/TAP reste la source de vérité. TShark extrait BVLC, NPDU et APDU : service, type et instance d'objet, propriété, valeur présente et erreur. Une source `passive` n'émet rien. Le mode `discovery` envoie un Who-Is sur le broadcast configuré toutes les cinq minutes ; les I-Am et échanges qui en découlent sont capturés par le même pipeline.

BACnet/SC repose sur TLS. Un certificat ou mot de passe peut être conservé par le gestionnaire de secrets, mais cela ne garantit pas le déchiffrement d'une session à clés éphémères. Dans ce cas, horodatage, IP, tailles et PCAP restent disponibles.

## Découverte réseau

Les scans sont des travaux courts réclamés atomiquement par le collecteur concerné. BACnet émet un Who-Is vers le broadcast choisi et extrait l'instance Device des I-Am. KNX émet un SearchRequest vers le groupe multicast choisi et extrait l'adresse de la gateway, son adresse individuelle et son nom lorsqu'ils sont publiés. Les résultats sont conservés dans `discovered_devices`.

Cette approche ne nécessite pas de SPAN. Elle ne voit cependant que les équipements qui répondent aux requêtes et les télégrammes reçus par les connexions ouvertes depuis la VM.

## Modbus/TCP

La capture passive indexe les transactions vues sur le réseau. Le mode `polling` ouvre une connexion TCP et lit uniquement les points activés. Le MVP prend en charge FC03/FC04, les types `uint16`, `int16`, `uint32`, `int32`, `float32` et `bool`, avec échelle et permutations d'octets/mots.

Les adresses sont des offsets protocolaires de 0 à 65535, pas la notation documentaire 4xxxx. Aucune écriture n'est émise. Le port 802 est capturé pour Modbus Security, mais la charge TLS reste opaque sans secrets de session compatibles.

## KNX multi-gateway

### Routing

Une écoute rejoint le multicast configuré, normalement `224.0.23.12:3671`. Les routeurs du même domaine publient leurs `RoutingIndication`. Plusieurs configurations utilisant le même groupe peuvent voir les mêmes datagrammes ; le collecteur élimine les doublons sur une fenêtre courte.

### Tunneling

Une tâche asynchrone est créée pour chaque gateway activée. Elle :

1. ouvre un socket UDP local ;
2. demande un tunnel KNXnet/IP link-layer ;
3. acquitte chaque `TunnelingRequest` ;
4. publie les indications cEMI ;
5. envoie un heartbeat après 50 secondes de silence ;
6. se reconnecte après une erreur sans interrompre les autres gateways.

Chaque tunnel consomme une connexion et généralement une adresse individuelle additionnelle sur la gateway. Le nombre de sessions disponibles dépend du modèle. Le mode Bus Monitor complet peut être exclusif ou indisponible sur un routeur ; le MVP utilise donc le mode link-layer adapté à une collecte continue.

### Secure

Le schéma accepte un `credential_id` et l'interface peut importer un keyring KNX, un PKCS#12 ou des secrets TLS. Le contenu est chiffré avant insertion. L'adaptateur KNX IP Secure n'est volontairement pas activé dans le collecteur actuel : sa mise en service doit inclure des tests avec les marques de gateways visées, la gestion des compteurs de séquence et la rotation des clés.

## API utile

| Méthode | Route | Usage |
| --- | --- | --- |
| GET | `/api/health` | Santé de l'API |
| GET | `/api/summary` | Vue d'ensemble |
| GET | `/api/frames?limit=50` | Dernières trames |
| GET | `/api/gateways` | Liste des gateways |
| POST | `/api/gateways` | Ajout routing/tunneling |
| POST | `/api/credentials` | Import chiffré d'un profil |
| PATCH | `/api/gateways/{id}/status` | État envoyé par le collecteur |
| POST | `/api/collector/telegram` | Télégramme normalisé interne |
| GET/POST | `/api/sources` | Sources BACnet et Modbus |
| GET/POST | `/api/sources/{id}/points` | Map de registres/points |
| GET | `/api/values` | Dernières valeurs techniques |
| POST | `/api/collector/value` | Valeur normalisée interne |
| GET/POST | `/api/scans` | Historique et lancement des scans |
| GET | `/api/scans/{id}/devices` | Équipements découverts |

Les deux dernières routes exigent `X-Internal-Token`. Avant exposition en production, le proxy doit recevoir un certificat TLS et l'interface doit être reliée à un fournisseur d'identité.

## Passage en production

- désactiver `DEMO_DATA` ;
- placer la VM sur un réseau d'administration séparé ;
- autoriser le multicast/IGMP nécessaire entre la sonde et les routeurs ;
- synchroniser la VM par NTP/PTP ;
- mesurer les pertes `dumpcap` avant d'augmenter le trafic observé ;
- remplacer la clé locale par Vault/KMS/HSM ;
- ajouter TLS et SSO au proxy ;
- tester chaque famille de gateway KNX avant d'activer Secure.
- valider les broadcasts BACnet et chaque map Modbus avec l'exploitant avant d'activer un mode émissif.
