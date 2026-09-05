#!/usr/bin/env bash
# run.sh - one-command local setup and start for HCG Knowledge Centre.
#
#   ./run.sh                 create .venv, install deps, init the DB, start the app
#   ./run.sh --setup-only    do everything except start the server
#   ./run.sh --port 8000     start on a specific port (same as LMS_PORT=8000 ./run.sh)
#   ./run.sh --host 0.0.0.0  listen on all interfaces
#   ./run.sh --no-debug      disable the Flask debugger / auto-reload
#
# Environment variables (all optional):
#   LMS_HOST, LMS_PORT   bind address and port. Default 127.0.0.1:5000; if 5000 is
#                        busy (macOS AirPlay Receiver uses it) the first free port in
#                        5050-5059 is used and announced.
#   LMS_DATABASE         SQLite file            (default ./users.db)
#   LMS_UPLOAD_FOLDER    upload directory       (default ./uploads)
#   LMS_SECRET_KEY       Flask session secret   (set this for anything shared)
#   LMS_DEBUG            1 = debugger + reload  (default 1)
#   PYTHON               interpreter used to create the venv (default python3)
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
LMS_HOST="${LMS_HOST:-127.0.0.1}"
PORT_REQUESTED="${LMS_PORT:-}"
SETUP_ONLY=0

usage() {
  cat <<'USAGE'
Usage: ./run.sh [--setup-only] [--port N] [--host H] [--no-debug] [--help]

  --setup-only   create .venv, install requirements, initialize the DB, then exit
  --port N       bind to port N (or set LMS_PORT). Default 5000, falling back to
                 the first free port in 5050-5059 when 5000 is busy
  --host H       bind address (or set LMS_HOST). Default 127.0.0.1
  --no-debug     run without the Flask debugger and auto-reload (LMS_DEBUG=0)

See the header of this script for all LMS_* environment variables.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --setup-only) SETUP_ONLY=1 ;;
    --port)       shift; PORT_REQUESTED="${1:-}" ;;
    --port=*)     PORT_REQUESTED="${1#*=}" ;;
    --host)       shift; LMS_HOST="${1:-}" ;;
    --host=*)     LMS_HOST="${1#*=}" ;;
    --no-debug)   export LMS_DEBUG=0 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python 3.8+
command -v "$PYTHON" >/dev/null 2>&1 || die "'$PYTHON' not found. Install Python 3.8+ or set PYTHON=/path/to/python3."
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || die "Python 3.8 or newer is required (found $("$PYTHON" --version 2>&1))."

# 2. Virtual environment
if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "Creating virtual environment in $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"

# 3. Dependencies - reinstalled only when requirements.txt changes
STAMP="$VENV_DIR/.requirements.sha256"
WANT="$("$VENV_PY" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt", "rb").read()).hexdigest())')"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  log "Installing dependencies from requirements.txt"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  printf '%s\n' "$WANT" > "$STAMP"
else
  log "Dependencies are up to date"
fi

# 4. Database - core schema, init_scripts/*.sql (once each), demo data
log "Initializing database"
"$VENV_PY" -m flask --app app init-db

if [ "$SETUP_ONLY" -eq 1 ]; then
  log "Setup complete. Start the app with ./run.sh"
  exit 0
fi

# 5. Port selection
port_busy() {
  "$VENV_PY" -c 'import socket, sys
s = socket.socket(); s.settimeout(0.2)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$1"
}
if [ -n "$PORT_REQUESTED" ]; then
  LMS_PORT="$PORT_REQUESTED"
  if port_busy "$LMS_PORT"; then die "Port $LMS_PORT is already in use."; fi
else
  LMS_PORT=5000
  if port_busy "$LMS_PORT"; then
    for candidate in 5050 5051 5052 5053 5054 5055 5056 5057 5058 5059; do
      if ! port_busy "$candidate"; then LMS_PORT="$candidate"; break; fi
    done
    [ "$LMS_PORT" -ne 5000 ] || die "Ports 5000 and 5050-5059 are all in use. Set LMS_PORT to a free port."
    log "Port 5000 is in use (on macOS that is usually AirPlay Receiver); using port $LMS_PORT"
  fi
fi
export LMS_HOST LMS_PORT

# 6. Run
log "Starting HCG Knowledge Centre at http://$LMS_HOST:$LMS_PORT"
exec "$VENV_PY" app.py
