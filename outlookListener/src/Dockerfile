ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION} AS release

RUN mkdir /app
WORKDIR /app

COPY outlookListener/src/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

COPY libblinkstick/src/myblinkstick /app/myblinkstick
COPY outlookListener/src/outlookListener.py /app/

CMD python outlookListener.py


FROM release AS debug

COPY debug.requirements.txt debug.requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r debug.requirements.txt
CMD python -m debugpy --wait-for-client \
           --listen 0.0.0.0:5678 \
           calendarListener.py

FROM release AS result
