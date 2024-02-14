ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION} AS release

RUN mkdir /app
WORKDIR /app

# node-ws provides `wscat`, useful for debugging the websocket connection
# Connect to the websocket (from inside the container) with
#   wscat --connect localhost:9099
COPY ledController/src/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

COPY ledController/src/ /app
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
     apt update \
  && apt install -y node-ws libusb-1.0-0-dev

COPY libblinkstick/src/myblinkstick /app/myblinkstick
COPY ledController/src/ /app/ledController
ENV PYTHONPATH=/app

CMD python ledController/ledController.py

HEALTHCHECK CMD python ledControllerHealthCheck.py


FROM release AS debug

COPY debug.requirements.txt debug.requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r debug.requirements.txt
CMD python -m debugpy \
           --listen 0.0.0.0:5678 \
           ledController/ledController.py

# By default, make the resultant container the release version
FROM release AS result