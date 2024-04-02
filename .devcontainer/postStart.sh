#!/bin/bash

set -x
set -o
set -u pipefail
# Purposefully not setting -e.  If a command fails, a subsequent command might still do useful
# work.

pip install -r /workspaces/blinkstick-notifier/bitbucket/src/requirements.txt \
            -r /workspaces/blinkstick-notifier/calendarListener/src/requirements.txt \
            -r /workspaces/blinkstick-notifier/ledController/src/requirements.txt \
            -r /workspaces/blinkstick-notifier/ledController/test/requirements.txt \
            -r /workspaces/blinkstick-notifier/libblinkstick/test/requirements.txt \
            -r /workspaces/blinkstick-notifier/outlookListener/src/requirements.txt \
            -r /workspaces/blinkstick-notifier/webhook/src/requirements.txt

docker compose pull
docker compose build