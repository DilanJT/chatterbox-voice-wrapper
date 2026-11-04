#!/bin/sh
# Kept for compatibility: same as `make register`.
exec sh "$(dirname "$0")/scripts/bootstrap.sh" register "$@"
