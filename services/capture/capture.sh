#!/usr/bin/env sh
set -eu
: "${CAPTURE_INTERFACE:?CAPTURE_INTERFACE est requis}"
mkdir -p /pcap
exec dumpcap -i "$CAPTURE_INTERFACE" -q -B 64 -s 0 \
  -f "${CAPTURE_FILTER:-udp port 3671 or tcp port 502 or tcp port 802 or udp portrange 47808-47823}" \
  -b "filesize:${PCAP_FILESIZE_KB:-100000}" -b "files:${PCAP_FILE_COUNT:-96}" \
  -w /pcap/bms.pcapng
