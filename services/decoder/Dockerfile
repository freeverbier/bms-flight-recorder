FROM python:3.12-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tshark && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir httpx==0.28.1
WORKDIR /app
COPY decoder.py .
CMD ["python", "decoder.py"]

