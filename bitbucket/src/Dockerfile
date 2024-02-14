ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION} AS release

RUN mkdir /app
WORKDIR /app

COPY bitbucket/src/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

COPY libblinkstick/src/myblinkstick /app/myblinkstick
COPY bitbucket/src /app/bitbucket/

CMD python bitbucket/bitbucket_listener.py
ENV PYTHONPATH=/app


FROM release AS debug

COPY debug.requirements.txt debug.requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r debug.requirements.txt
CMD python -m debugpy \
           --listen 0.0.0.0:5678 \
           bitbucket/bitbucket_listener.py

# By default, make the resultant container the release version
FROM release AS result
