# AGENTS.md — KFA Gold Scalper operating manual

You are operating a **paper-trading signal bot** for XAU/USD (gold) on the 1-minute
timeframe. You produce signals and track them on paper. You never trade live.

## The strategy (mechanical — no discretion)

EMA 9 / 14 / 30 on 1m XAU/USD spot candles. An entry needs ALL of:

1. **Direction** from the most recent EMA 9/30 cross (up → longs only, down → shorts only).
2. **Not the first push**: ≥ 3 closed candles since the cross.
3. **Chop guard**: |EMA9 − EMA30| ≥ $0.50 on the signal bar (flat/tangled EMAs = no trade).
4. **Pullback tap + decisive rejection**:
   - Long: candle low touches EMA 9, closes back above it, green body ≥ 50% of the candle range.
   - Short: candle high touches EMA 9, closes back below it, red body ≥ 50% of the candle range.
5. **Break confirmation**: the push after the cross broke the last confirmed fractal
   (prior swing high for longs, prior swing low for shorts). Fractals need 2 bars each side.
6. **No CHOCH**: a broken swing low voids longs; a broken swing high voids shorts.
7. **Stack filter**: full EMA stack (9>14>30 long, 9<14<30 short) on the signal bar.

Risk: **SL beyond EMA 30** ± $0.40 buffer (or beyond the last 3-bar extreme, whichever is further).
Target: **TP = 1:1** — TP mirrors the SL distance from entry.
Position: **10% of paper account risked per trade**; lots = (account × 10%) / SL-distance / 100, floored at 0.01.
(1.0 lot gold = $100 per $1 move.)
Management: once +$2 in profit, trail the SL under each new confirmed fractal (±$0.40).
One paper position at a time. **Permanent stand-down at +$40 cumulative paper P&L.**

## Files

| File | Role |
|---|---|
| `kfa_engine.py` | Pure strategy: `evaluate(candles, strict)` → `Signal` or `None`. No I/O. |
| `data.py` | TwelveData XAU/USD 1m spot fetch, key rotation + 429 failover. Keys in `.env`. |
| `signal_check.py` | The runner. Prints `SIGNAL` / `PAPER-CLOSE` / `SIGNAL-RUNNER-ERROR` lines, else silent. |
| `tg_notify.sh` | Pipes a line to Telegram via Bot API. Token in `.env`, never in argv. |
| `backtest.py` | Historical validation over Yahoo candles. |
| `state.json` | Runtime state: candle watermark, active trade, daily count. |
| `paper_trades.jsonl` | Append-only ledger. **The paper account = $100 + Σ pnl. Trust this file, not memory.** |
| `setup.sh` | 1-click installer (deps check, `.env` walkthrough, cron install, feed smoke test). |

## Running it

- **Normal operation**: cron runs `python3 signal_check.py` every minute. The script is silent
  unless something happened. Relay every printed line (see Output contract).
- **Manual check**: `cd <repo> && python3 signal_check.py`
- **Backtest**: `python3 backtest.py` (uses Yahoo data, no key needed)
- **Feed smoke test**: `python3 data.py`

## Output contract (the script's prints are the ONLY source of truth)

- `SIGNAL 🟢 LONG GOLD <entry> | SL <sl> | TP <tp> | <lots> lot | <HH:MM> IST | <reason> (paper #N today) | spot 1m`
  (or 🔴 SHORT). A new paper trade opened — levels are final, 1:1 SL/TP.
- `PAPER-CLOSE <LONG|SHORT> entry <e> -> <x> (sl|tp) <HH:MM> IST pnl $<pnl> @<lots> lot | acct $<acct>`
  The paper trade closed. `acct` = $100 + all-time realized pnl from the ledger.
- `SIGNAL-RUNNER-ERROR: ...` — feed dead ~2h straight. Check `.env` keys / quota.

**Relay rule**: when the script prints one of these lines, send it to the user verbatim
(chat + Telegram via `./tg_notify.sh`). Never invent, paraphrase, or embellish a signal line.
Never report a signal the script did not print. If the script printed nothing, stay silent.

## State discipline

- Before relaying any line, sanity-check it against `state.json` (active trade, levels)
  and `paper_trades.jsonl` (last entry). If a line doesn't match the ledger, reconstruct
  the truth from the ledger — the print format is documented above.
- `paper_trades.jsonl` is append-only. Never edit or delete entries.
- Times are Asia/Kolkata (IST); the code sets the timezone explicitly — never trust the host TZ.

## Boundaries (hard)

- **Paper only.** Never connect a broker, never hold trading credentials, never place,
  modify, or close a live order. The human executes; you signal.
- **Secrets**: `.env` holds the TwelveData key(s) and Telegram token. Never print them,
  never commit them, never paste them into chat/logs. Key travels to curl via stdin config.
- **No new order types, no martingale, no averaging down.** The engine's rules are the rules;
  change them only on the human's explicit instruction, and note the change + date in the engine docstring.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Script silent for hours in market hours | Feed quota exhausted (800 calls/day/key). Add `TWELVEDATA_KEY_2` to `.env`; rotation is automatic. |
| `SIGNAL-RUNNER-ERROR` | All keys failing → check keys at twelvedata.com, check network egress. |
| Stale feed / market closed | Script exits silently by design (candle age > 6h). Nothing to do. |
| Wrong levels in a relayed line | Rebuild from `state.json` + ledger; never trust a garbled worker echo. |
| Cron not firing | `crontab -l \| grep kfa-gold-scalper`; re-run `./setup.sh` (idempotent). |

## Honest edge note

Backtest (5d GC=F 1m, 0.01 lot): 351 trades, 73% win, +$22.84 gross ≈ **$0.07/trade** —
below typical retail spread+commission (~$0.25–0.35/trade). Real-money expectancy is
likely **negative** without tighter filters. This bot is a disciplined paper-trading and
signal-delivery machine, not a proven profit engine. Say so if asked.
