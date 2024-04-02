#!/bin/bash

set -x
set -o
set -u pipefail
# Purposefully not setting -e.  If a command fails, a subsequent command might still do useful
# work.

find . -name requirements.txt -print | xargs printf -- '-r %s ' | xargs pip install

docker compose pull
docker compose build