FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier TOUS les fichiers Python et le module bacnet_parse
COPY *.py ./
COPY bacnet_parse/ ./bacnet_parse/

CMD ["python", "-u", "collector.py"]
