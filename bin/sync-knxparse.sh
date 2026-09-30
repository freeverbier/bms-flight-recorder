#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
rm -rf services/api/app/knxparse
cp -r services/knx-collector/knxparse services/api/app/knxparse
