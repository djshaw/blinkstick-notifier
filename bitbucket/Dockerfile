FROM python

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install prometheus_client \
                 pymongo \
                 pyyaml \
                 requests \
                 websocket-client

RUN mkdir /app

COPY bitbucket/bitbucket.py \
     bitbucket/schema.sql \
     heap/heap.py \
     workunit/workunit.py \
     web/navbar.py \
     websocketClient/websocketClient.py \
     /app/

WORKDIR /app
CMD python bitbucket.py

