FROM python

# node-ws provides `wscat`, useful for debugging the websocket connection
# Connect to the websocket (from inside the container) with
#   wscat --connect localhost:9099
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    pip3 install blinkstick \
                 jsonschema \
                 prometheus_client \
                 pyusb \
                 pyyaml \
                 rel \
                 requests \
                 simple-websocket-server \
                 websocket-client \
  && apt update \
  && apt install -y node-ws libusb-1.0-0-dev

RUN mkdir /app

COPY heap/heap.py \
     ledController/blinkstickThread.py \
     ledController/config.yml \
     ledController/ledController.py \
     ledController/ledController.yml \
     ledController/ledControllerHealthCheck.py \
     ledController/receive.schema.json \
     ledController/send.schema.json \
     web/navbar.py \
     /app/

WORKDIR /app
CMD python ledController.py

HEALTHCHECK CMD python ledControllerHealthCheck.py

