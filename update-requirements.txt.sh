#!/bin/bash

set -e
set -o pipefail
set -u
set -x

HERE=$( dirname $( realpath $0 ) )
LIBBLINKSTICK_REQUIREMENTS_VOLUME="--volume $HERE/libblinkstick/src/requirements.root.txt:/app/libblinkstick/requirements.txt"
PYTHON=python:3.12

# bitbucket
docker run --volume $HERE/bitbucket/src/requirements.root.txt:/app/bitbucket/requirements.txt \
           --volume $HERE/update-requirements.txt-in-docker.sh:/update-requirements.txt-in-docker.sh \
           $LIBBLINKSTICK_REQUIREMENTS_VOLUME \
           --network host \
           $PYTHON \
           bash /update-requirements.txt-in-docker.sh > $HERE/bitbucket/src/requirements.txt


# calendar-listener
docker run --volume $HERE/calendarListener/src/requirements.root.txt:/app/calendarListener/requirements.txt \
           --volume $HERE/update-requirements.txt-in-docker.sh:/update-requirements.txt-in-docker.sh \
           $LIBBLINKSTICK_REQUIREMENTS_VOLUME \
           --network host \
           $PYTHON \
           bash /update-requirements.txt-in-docker.sh > $HERE/calendarListener/src/requirements.txt


# ledController
docker run --volume $HERE/ledController/src/requirements.root.txt:/app/ledController/requirements.txt \
           --volume $HERE/update-requirements.txt-in-docker.sh:/update-requirements.txt-in-docker.sh \
           $LIBBLINKSTICK_REQUIREMENTS_VOLUME \
           --network host \
           $PYTHON \
           bash /update-requirements.txt-in-docker.sh > $HERE/ledController/src/requirements.txt

# outlook-listener
docker run --volume $HERE/outlookListener/src/requirements.root.txt:/app/outlookListener/requirements.txt \
           --volume $HERE/update-requirements.txt-in-docker.sh:/update-requirements.txt-in-docker.sh \
           $LIBBLINKSTICK_REQUIREMENTS_VOLUME \
           --network host \
           $PYTHON \
           bash /update-requirements.txt-in-docker.sh > $HERE/outlookListener/src/requirements.txt


# webhook
docker run --volume $HERE/update-requirements.txt-in-docker.sh:/update-requirements.txt-in-docker.sh \
           $LIBBLINKSTICK_REQUIREMENTS_VOLUME \
           --network host \
           $PYTHON \
           bash /update-requirements.txt-in-docker.sh > $HERE/webhook/src/requirements.txt


