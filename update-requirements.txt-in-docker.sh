#!/bin/bash

set -e
set -o pipefail
set -u
set -x

REQUIREMENTS=$( find /app -name "requirements.*txt" | sed -e "s/^/-r /g" | tr '\n' ' ' )
pip3 install $REQUIREMENTS 1>&2
pip3 freeze

