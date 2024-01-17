FROM python

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install prometheus_client \
                 pyyaml \
                 websocket-client

RUN mkdir /app

COPY web/navbar.py \
     webhook/webhook.py \
     websocketClient/websocketClient.py \
     /app/

WORKDIR /app
CMD python webhook.py

