#!/bin/bash
# macOS: double-click to run the first-time setup.
cd "$(dirname "$0")"
sh scripts/bootstrap.sh setup 2>&1 | tee logs/setup.log
