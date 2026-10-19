"""
Live KFA signal runner. Called every 1 minute by cron.
- Fetches fresh XAU/USD 1m SPOT candles (TwelveData, key in .env).
- Walks new closed candles through the KFA engine.
- Opens at most ONE paper trade at a time; NO daily signal cap — fires every
  strict-filter entry until the +$40 cumulative paper target, then stands down.
- Trails +$2 winners under each new fractal.
- Prints SIGNAL / PAPER-CLOSE blocks ONLY when something happened.
  Silent runs print nothing — the caller (cron pipe or an AI agent) relays
  those lines to chat / Telegram.
- Stays silent on stale feed (market closed) and on transient fetch failures;
  prints SIGNAL-RUNNER-ERROR only after ~2h of consecutive failures.

State: state.json (watermark, active trade, daily count).
Paper log: paper_trades.jsonl (append-only; the account ledger).

Paper only. This script never touches a broker and never places live orders.
"""
import sys, os, json, time, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import fetch_spot_1m
from kfa_engine import evaluate, bearish_fractals, bullish_fractals, last_confirmed

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))  # explicit: never trust the cell's TZ


def ist_hm(ts):
    return datetime.datetime.fromtimestamp(ts, tz=IST).strftime("%H:%M")


def today_ist():
    # Explicit IST date for the trading-day boundary (midnight IST).
    return datetime.datetime.now(tz=IST).strftime("%Y-%m-%d")


HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "paper_trades.jsonl")
PROFIT_TARGET = 40.0   # $ cumulative all-time paper profit, then stand down
RISK_PCT = 10.0        # % of paper account risked per trade; lots sized off the real SL distance


def total_pnl():
    """Realized paper P&L, all-time cumulative, from the trade log."""
    total = 0.0
    if os.path.exists(LOG):
        for line in open(LOG):
            try:
                t = json.loads(line)
            except Exception:
                continue
            total += t.get("pnl", 0) or 0
    return round(total, 2)


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"last_ts": 0, "active": None, "signals_today": 0, "day": ""}


def save_state(s):
    json.dump(s, open(STATE, "w"), indent=1)


def log_trade(t):
    with open(LOG, "a") as f:
        f.write(json.dumps(t) + "\n")


def trail_sl(active, candles, i):
    e, sl = active["entry"], active["sl"]
    c = candles[i]
    profit = (c.c - e) if active["side"] == "long" else (e - c.c)
    if profit >= 2.0:
        if active["side"] == "long":
            lf = last_confirmed(bullish_fractals(candles[:i+1]), i)
            if lf and lf[1] - 0.4 > sl:
                return lf[1] - 0.4, True
        else:
            hf = last_confirmed(bearish_fractals(candles[:i+1]), i)
            if hf and hf[1] + 0.4 < sl:
                return hf[1] + 0.4, True
    return sl, False


def main():
    st = load_state()
    day = today_ist()
    if st["day"] != day:
        st.update({"day": day, "signals_today": 0})

    try:
        candles = fetch_spot_1m(250)  # TwelveData XAU/USD 1m spot
    except Exception as e:
        # Stay silent on transient/quota failures; only page after ~2h of
        # consecutive failures so one dead day doesn't spam the chat.
        fails = st.get("fetch_fails", 0) + 1
        st["fetch_fails"] = 0 if fails >= 120 else fails
        save_state(st)
        if fails >= 120:
            print(f"SIGNAL-RUNNER-ERROR: spot feed failed 120x in a row: {e}")
        return
    st["fetch_fails"] = 0
    if not candles:
        return  # nothing usable fetched -> stay silent
    if time.time() - candles[-1].ts > 6 * 3600:
        return  # market closed / stale feed -> stay silent
    if st["last_ts"] == 0:
        # First run ever (or lost state.json): seed the watermark at the
        # newest candle and start fresh next run — do NOT walk history as
        # if it were live setups.
        st["last_ts"] = candles[-1].ts
        save_state(st)
        return

    new = [c for c in candles if c.ts > st["last_ts"]]
    if not new:
        return
    base = len(candles) - len(new)
    save_state(st)

    for k, c in enumerate(new):
        i = base + k
        if st["active"] is None:
            pnl = total_pnl()
            if pnl >= PROFIT_TARGET:
                continue  # target hit: stand down
            sig = evaluate(candles[:i+1], strict={"stack", "decisive"})
            if sig:
                # 10%-risk sizing: lots = (account * risk%) / stop-distance.
                # 1.0 lot gold = $100/point, so lots = risk$ / sl_dist / 100, floored to 0.01
                acct = 100.0 + total_pnl()
                sl_dist = abs(sig.entry - sig.sl) or 1.0
                lots = max(0.01, math.floor(acct * RISK_PCT / 100.0 / sl_dist) / 100.0)
                st["active"] = {"side": sig.side, "entry": sig.entry,
                                "sl": sig.sl, "tp": sig.tp, "lots": lots,
                                "open_ts": sig.bar_ts, "reason": sig.reason}
                st["signals_today"] += 1
                arrow = "🟢 LONG" if sig.side == "long" else "🔴 SHORT"
                sig_time = ist_hm(sig.bar_ts)
                print(f"SIGNAL {arrow} GOLD {sig.entry:.1f} | SL {sig.sl:.1f} | TP {sig.tp:.1f} "
                      f"| {lots:.2f} lot | {sig_time} IST | {sig.reason} (paper #{st['signals_today']} today)"
                      f" | spot 1m")
        else:
            a = st["active"]
            a["sl"], trailed = trail_sl(a, candles, i)
            hit_sl = (c.l <= a["sl"]) if a["side"] == "long" else (c.h >= a["sl"])
            hit_tp = (c.h >= a["tp"]) if a["side"] == "long" else (c.l <= a["tp"])
            if hit_sl or hit_tp:
                px = a["sl"] if hit_sl else a["tp"]
                lots = a.get("lots", 0.01)
                pnl = (px - a["entry"]) if a["side"] == "long" else (a["entry"] - px)
                pnl *= lots * 100.0  # 1.0 lot gold = $100 per $1 move
                rec = {**a, "exit": round(px, 2), "exit_ts": c.ts,
                       "pnl": round(pnl, 2), "why": "sl" if hit_sl else "tp",
                       "trailed": trailed}
                log_trade(rec)
                acct = 100.0 + total_pnl()  # $100 paper account
                close_time = ist_hm(c.ts)
                print(f"PAPER-CLOSE {a['side'].upper()} entry {a['entry']:.1f} -> {px:.1f} "
                      f"({rec['why']}) {close_time} IST pnl ${pnl:+.2f} @{lots:.2f} lot | acct ${acct:.2f}")
                st["active"] = None

    st["last_ts"] = candles[-1].ts
    save_state(st)


if __name__ == "__main__":
    main()
