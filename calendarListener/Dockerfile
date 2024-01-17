FROM python

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install google-auth \
                 google-auth-httplib2 \
                 google-api-python-client \
                 google-auth-oauthlib \
                 prometheus_client \
                 requests \
                 pyyaml \
                 websocket-client

RUN mkdir /app

COPY calendarListener/calendarListener.py \
     web/navbar.py \
     /app/

WORKDIR /app
CMD python calendarListener.py

