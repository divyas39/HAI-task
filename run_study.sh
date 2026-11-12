#!/bin/sh
# Serve the review study from this laptop and print a public link anyone can open.
# Usage: ./run_study.sh     (ctrl-c to stop and close the link)
set -e
cd "$(dirname "$0")"

# Secrets are generated once and reused, so a restart doesn't invalidate live sessions.
if [ ! -f .env.study ]; then
  python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32)); \
              print('EXPORT_TOKEN=' + secrets.token_urlsafe(16))" > .env.study
  echo "generated .env.study (gitignored)"
fi
set -a; . ./.env.study; set +a
export DB_PATH="${DB_PATH:-$PWD/study.db}"

.venv/bin/gunicorn app:app --bind 127.0.0.1:5000 --workers 1 --access-logfile - &
# ponytail: single worker on purpose -- SQLite is one file, extra workers would fight over it.
trap 'kill $! 2>/dev/null' EXIT INT TERM
sleep 2

echo
echo "  data file : $DB_PATH"
echo "  your CSV  : <link below>/export?token=$EXPORT_TOKEN"
echo "  share the plain https:// link Cloudflare prints, nothing after it"
echo
exec cloudflared tunnel --url http://localhost:5000
