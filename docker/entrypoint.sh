#!/bin/sh
set -eu
umask 077
python /usr/local/bin/bootstrap.py
exec "$@"
