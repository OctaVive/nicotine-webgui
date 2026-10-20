#!/bin/sh
set -eu
docker compose build
exec docker compose up
