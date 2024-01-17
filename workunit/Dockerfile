FROM python

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install prometheus_client

RUN mkdir -p /app
WORKDIR /app

