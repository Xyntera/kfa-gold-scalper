# KFA Gold Scalper

Automated **paper-trading signal bot** for XAU/USD (gold) on the 1-minute timeframe,
implementing the EMA 9/14/30 scalping method: cross → pullback tap of EMA 9 →
decisive rejection → break confirmation. 1:1 SL/TP, 10% risk sizing, fractal
trailing, permanent stand-down at +$40 paper profit.

**Paper only.** This bot produces signals and tracks them in a local ledger.
It never connects to a broker and never places live orders — you execute.

## 1-click setup

```bash
git clone https://github.com/Xyntera/kfa-gold-scalper.git
cd kfa-gold-scalper
./setup.sh
```

`setup.sh` checks for python3/curl/cron (no pip packages — stdlib only), walks you
through two things, installs a 1-minute cron job, and smoke-tests the feed:

1. **TwelveData API key** — free at [twelvedata.com](https://twelvedata.com) (800 calls/day).
   1-minute polling needs ~1,440 calls/day, so add 2 keys for full-day coverage —
   the fetcher round-robins them automatically with failover.
2. **Telegram alerts** (recommended) — a bot token from `@BotFather` and your chat id
   from `@userinfobot`. Signals land on your phone the minute they fire.

Keys live in `.env` (chmod 600, never committed).

## What you get

Every minute, `signal_check.py` fetches fresh XAU/USD 1m spot candles and walks them
through the strategy engine. When something happens you get a line like:

```
SIGNAL 🟢 LONG GOLD 4185.9 | SL 4180.8 | TP 4191.0 | 0.02 lot | 11:18 IST | cross up @11:09, pullback tap 9, bounce, high 4185.0 broken (paper #17 today) | spot 1m
PAPER-CLOSE SHORT entry 4177.4 -> 4174.0 (tp) 12:01 IST pnl $+10.23 @0.03 lot | acct $114.21
```

These go to `signals.log` and your Telegram. Quiet minutes print nothing.

## For AI agents

**`AGENTS.md`** is the complete operating manual: the mechanical strategy rules, the
file map, the output contract, relay rules, state discipline, hard boundaries, and
troubleshooting. Point any agent at this repo and it can operate, supervise, and
extend the bot.

## Files

| File | Role |
|---|---|
| `AGENTS.md` | Agent operating manual (start here if you're an AI) |
| `kfa_engine.py` | Pure strategy engine — `evaluate(candles)` → signal or `None` |
| `signal_check.py` | 1-minute runner: signals, paper closes, fractal trailing |
| `data.py` | TwelveData spot feed with key rotation |
| `tg_notify.sh` | Telegram delivery via Bot API |
| `backtest.py` | Historical validation |
| `setup.sh` | 1-click installer |

## The rules, briefly

- Direction from the latest EMA 9/30 cross; ≥3 bars after the cross; |EMA9−EMA30| ≥ $0.50
- Entry: pullback taps EMA 9 and rejects decisively (body ≥ 50% of range), prior fractal broken, no CHOCH, full EMA stack
- SL beyond EMA 30 (±$0.40) · TP = 1:1 · 10% account risk/trade · trail +$2 winners under new fractals
- One paper position max · no daily cap · stand down forever at +$40 cumulative

## Honest note

Backtested edge is thin (≈$0.07/trade gross at 0.01 lot, below spread+commission).
Treat this as a disciplined signal + paper-tracking machine, not a proven profit engine.

## License

MIT — do what you want, at your own risk.
