ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION} AS release

RUN mkdir -p /app/calendarListener
WORKDIR /app

COPY ./calendarListener/src/requirements.txt requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

COPY libblinkstick/src/myblinkstick /app/myblinkstick/
COPY calendarListener/src/calendarListener.py /app/calendarListener/
ENV PYTHONPATH=/app

CMD python calendarListener/calendarListener.py


FROM release AS debug

COPY debug.requirements.txt debug.requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r debug.requirements.txt
CMD python -m debugpy \
           --listen 0.0.0.0:5678 \
           calendarListener/calendarListener.py

# By default, make the resultant container the release version
FROM release AS result
