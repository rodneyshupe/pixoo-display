#!/usr/bin/env bash
# Copy this project to a Docker host over SSH and (re)start it there. Needs rsync and ssh on this machine, Docker Compose on the host.
#   ./deploy.sh root@192.168.1.10                       # to /opt/stacks/pixoo-display
#   ./deploy.sh user@host /srv/stacks/pixoo-display     # another folder
#   SSH_OPTS="-i ~/.ssh/mykey" ./deploy.sh root@host    # extra ssh options
# The host keeps its own .env and .env.secret (never overwritten, never deleted). On the first run it creates .env from .env.example
# and stops so you can set PIXOO_HOST. Settings, picks and animations live in the data folder (APPDATA_ROOT), not here.
set -euo pipefail
[ $# -ge 1 ] || { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
HOST="$1"; DIR="${2:-/opt/stacks/pixoo-display}"; SSH_OPTS="${SSH_OPTS:-}"
cd "$(dirname "$0")"
echo "== sending to $HOST:$DIR"
ssh $SSH_OPTS "$HOST" "mkdir -p '$DIR'"
rsync -rc --itemize-changes --exclude .git --exclude .github --exclude .env --exclude .env.secret --exclude __pycache__ --exclude .DS_Store \
      -e "ssh $SSH_OPTS" ./ "$HOST:$DIR/" | grep -v '^\.d' || true
ssh $SSH_OPTS "$HOST" "cd '$DIR' && if [ ! -f .env ]; then cp .env.example .env && echo 'Created .env from .env.example: set PIXOO_HOST (and TZ), then run this again.' && exit 3; fi && docker compose config -q && docker compose up -d --build && sleep 8 && docker compose ps"
