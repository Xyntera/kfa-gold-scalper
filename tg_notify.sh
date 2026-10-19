#!/usr/bin/env bash
# tg_notify.sh — send a signal line to Telegram via the Bot API.
# Message text: stdin (or $1).
# Credentials come from the repo-local .env (0600, never committed):
#   TELEGRAM_BOT_TOKEN=<bot token from @BotFather>
#   TELEGRAM_CHAT_ID=<your numeric chat id — message @userinfobot to get it>
# The token is passed to curl via a config file on stdin, never in argv.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"

if [ -n "${1:-}" ]; then MSG="$1"; else MSG="$(cat)"; fi
[ -n "$MSG" ] || { echo '{"fatal":"empty message"}'; exit 2; }
[ -r "$ENV_FILE" ] || { echo '{"fatal":".env unreadable — copy .env.example to .env"}'; exit 2; }

TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
CHAT_ID="$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo '{"fatal":"TELEGRAM_BOT_TOKEN missing in .env"}'; exit 2; }
[ -n "$CHAT_ID" ] || { echo '{"fatal":"TELEGRAM_CHAT_ID missing in .env"}'; exit 2; }

# URL-encode the message with python3 (stdlib only)
ENCODED="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read()))' <<<"$MSG")"
printf 'url = "https://api.telegram.org/bot%s/sendMessage?chat_id=%s&text=%s"\n' \
  "$TOKEN" "$CHAT_ID" "$ENCODED" \
  | curl -s -m 20 -K - -o /dev/null -w '%{http_code}\n'
