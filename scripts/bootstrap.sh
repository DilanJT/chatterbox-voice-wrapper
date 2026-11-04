#!/bin/sh
# Installs uv if needed, then runs scripts/manage.py with a managed Python 3.11.
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv (Python package manager)"
  if command -v curl >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh
  else wget -qO- https://astral.sh/uv/install.sh | sh; fi
  export PATH="$HOME/.local/bin:$PATH"
fi
UV="$(command -v uv)"; export UV
exec "$UV" run --no-project --python 3.11 scripts/manage.py "$@"
