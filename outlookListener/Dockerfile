FROM python

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install msal \
		 prometheus_client \
		 pyyaml \
		 simple-websocket-server \
		 websocket-client

RUN mkdir /app

COPY heap/heap.py \
     outlookListener/outlookListener.py \
     web/navbar.py \
     websocketClient/websocketClient.py \
     workunit/workunit.py \
     /app/

WORKDIR /app
CMD python outlookListener.py

