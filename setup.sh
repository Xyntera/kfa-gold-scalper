#!/usr/bin/env bash
# setup.sh — 1-click installer for the KFA gold scalper.
#   git clone <repo> && cd kfa-gold-scalper && ./setup.sh
# What it does:
#   1. checks python3 + curl exist (stdlib only, no pip packages needed)
#   2. creates .env from .env.example and walks you through the keys
#   3. installs a cron job that runs the signal check every minute and
#      pushes SIGNAL / PAPER-CLOSE lines to your Telegram
#   4. smoke-tests the data feed once
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "== KFA gold scalper setup =="
command -v python3 >/dev/null || { echo "need python3"; exit 1; }
command -v curl >/dev/null || { echo "need curl"; exit 1; }
command -v crontab >/dev/null || { echo "need cron (crontab not found)"; exit 1; }
echo "python3 + curl + cron: ok (no pip packages needed)"

chmod +x tg_notify.sh

# --- .env ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env"
fi
chmod 600 .env

need_key() { # need_key VAR "prompt"
  local cur
  cur="$(grep -E "^$1=" .env | cut -d= -f2- | tr -d '[:space:]')"
  if [ -z "$cur" ]; then
    read -rsp "$2: " val; echo
    if [ -n "$val" ]; then
      if grep -qE "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$val|" .env
      else
        echo "$1=$val" >> .env
      fi
    fi
  else
    echo "$1: already set"
  fi
}

echo
echo "-- TwelveData (free at https://twelvedata.com, 800 calls/day/key) --"
echo "1-minute polling needs ~1,440 calls/day: add 2 keys for full-day coverage."
need_key "TWELVEDATA_KEY" "TwelveData key 1"
read -rp "Add a second TwelveData key? (y/N) " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  need_key "TWELVEDATA_KEY_2" "TwelveData key 2"
fi

echo
echo "-- Telegram alerts (recommended: signals go straight to your phone) --"
echo "1) @BotFather -> /newbot -> token | 2) @userinfobot -> your chat id | 3) message your new bot once"
read -rp "Set up Telegram now? (Y/n) " yn
if [[ ! "$yn" =~ ^[Nn]$ ]]; then
  need_key "TELEGRAM_BOT_TOKEN" "Bot token"
  need_key "TELEGRAM_CHAT_ID" "Your chat id"
fi
chmod 600 .env

# --- cron: every minute, relay signal lines to Telegram + signals.log ---
PY="$(command -v python3)"
CRON_LINE="* * * * * cd $HERE && $PY signal_check.py 2>>cron.log | grep -E '^(SIGNAL|PAPER-CLOSE|SIGNAL-RUNNER-ERROR)' | while IFS= read -r line; do echo \"\$line\" >> signals.log; echo \"\$line\" | ./tg_notify.sh >>cron.log 2>&1; done # kfa-gold-scalper"
if crontab -l 2>/dev/null | grep -q "kfa-gold-scalper"; then
  echo "cron job already installed"
else
  (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
  echo "cron job installed: signal check every minute"
fi

# --- smoke test: one real feed fetch ---
echo
echo "-- smoke test: fetching 5 spot candles --"
if python3 data.py; then
  echo "feed ok"
else
  echo "feed FAILED — check TWELVEDATA_KEY in .env"
  exit 1
fi

echo
echo "== done =="
echo "Signals will print to signals.log and hit your Telegram every minute."
echo "Paper ledger: paper_trades.jsonl | state: state.json"
echo "Read AGENTS.md to hand this to any AI agent as its operating manual."
