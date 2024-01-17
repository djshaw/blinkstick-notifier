#!/bin/bash

set -x

docker network create promtail_testing_default

PROMTAIL="docker run --rm --interactive --network promtail_testing_default --volume $( dirname $( dirname $( realpath $0 ) ) )/promtail-config.yaml:/promtail-config.yaml:ro grafana/promtail:2.9.2"

LOG_CLI="docker run --rm --network promtail_testing_default --env LOKI_ADDR=http://loki:3100 grafana/logcli:2.9.2-amd64"

docker-compose --project-name promtail_testing down --rmi all --volumes || true
docker-compose --project-name promtail_testing up --detach --renew-anon-volumes loki || true

# TODO: tests for INFO, WARN, ERROR, EXCEPTION
( cat <<EOF
{"log":"INFO:big long info message\\n","stream":"stderr","attrs":{"tag":"blinkstick_outlook-listener|blinkstick_outlook-listener_1|sha256:a5e164d1b144e1e39829c2047412ddd18da0e31b135dcdb4f329ede68a7ff1e5|b9f09db02b1b0a822a1ee37e61100b7c670979aa1b1953d3f4376dd4141061ff"},"time":"2023-11-16T14:41:56.83122765Z"}
{"log":"DEBUG:exceedingly long debug message\\n","stream":"stderr","attrs":{"tag":"blinkstick_outlook-listener|blinkstick_outlook-listener_1|sha256:a5e164d1b144e1e39829c2047412ddd18da0e31b135dcdb4f329ede68a7ff1e5|b9f09db02b1b0a822a1ee37e61100b7c670979aa1b1953d3f4376dd4141061ff"},"time":"2023-11-16T14:41:56.83122765Z"}
EOF
) | $PROMTAIL -config.file=/promtail-config.yaml \
	      -client.url=http://loki:3100 \
	      -inspect \
	      -stdin
#$LOG_CLI labels
$LOG_CLI query '{level="DEBUG"}'


docker-compose --project-name promtail_testing down --rmi all --volumes

