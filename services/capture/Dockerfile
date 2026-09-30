FROM debian:12-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tshark && rm -rf /var/lib/apt/lists/*
COPY capture.sh /capture.sh
RUN chmod +x /capture.sh
ENTRYPOINT ["/capture.sh"]

