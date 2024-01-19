#!/bin/bash

set -e
set -o pipefail
set -u

docker build . --tag check-jsonschema

CHECK_JSONSCHEMA="docker run --rm --interactive --volume $( realpath $( dirname $0 )/../ ):/app:ro check-jsonschema check-jsonschema --color always"

for SCHEMA_FILE in $( cd .. ; ls *.schema.json ) ; do
    echo $SCHEMA_FILE
    $CHECK_JSONSCHEMA --check-metaschema /app/$SCHEMA_FILE

    SCHEMA_NAME=${SCHEMA_FILE%.*}
    SCHEMA_NAME=${SCHEMA_NAME%.*}
    if [ -d $SCHEMA_NAME ] ; then
        for SAMPLE_FILE in $( cd $SCHEMA_NAME ; ls ) ; do
            echo validating $SCHEMA_NAME/$SAMPLE_FILE against $SCHEMA_FILE
            $CHECK_JSONSCHEMA --schemafile /app/$SCHEMA_FILE /app/test/$SCHEMA_NAME/$SAMPLE_FILE
        done
    fi
done

