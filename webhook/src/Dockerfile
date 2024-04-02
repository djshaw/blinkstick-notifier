ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION} AS release

RUN mkdir -p /app/webhook
WORKDIR /app

COPY webhook/src/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --requirement requirements.txt

COPY libblinkstick/src/myblinkstick /app/myblinkstick/
COPY webhook/src/webhook_listener.py /app/webhook/
ENV PYTHONPATH=/app

CMD python webhook/webhook_listener.py


FROM release AS debug

COPY debug.requirements.txt debug.requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r debug.requirements.txt
CMD python -m debugpy \
           --listen 0.0.0.0:5678 \
           webhook/webhook_listener.py

FROM release AS result
