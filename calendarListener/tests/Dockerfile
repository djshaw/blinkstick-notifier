FROM python

# TODO: put pip3 dependencies in a requirements.txt file
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install google-auth \
                 google-auth-httplib2 \
                 google-api-python-client \
                 google-auth-oauthlib \
                 prometheus_client \
                 requests \
                 pyyaml \
                 websocket-client

RUN mkdir -p /app

COPY . /app/

WORKDIR /app/tests
CMD python CalendarListenerTest.py

