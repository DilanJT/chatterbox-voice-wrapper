#!/bin/sh
# Kept for compatibility: same as `make setup`.
exec sh "$(dirname "$0")/scripts/bootstrap.sh" setup "$@"
