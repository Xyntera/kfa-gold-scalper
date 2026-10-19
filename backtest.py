"""
Backtest the KFA engine over historical candles.
Entry at signal-bar close. Intrabar SL/TP check on following bars
(conservative: if both hit in one bar, SL counts first). Trailing:
once +$2 in profit, trail SL under each new confirmed fractal.
"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from data import fetch
from kfa_engine import evaluate, bearish_fractals, bullish_fractals, last_confirmed, DOLLARS_PER_POINT


def backtest(candles, verbose=False, strict=False):
    trades = []
    active = None
    for i in range(40, len(candles)):
        if active is None:
            sig = evaluate(candles[:i+1], strict=strict)
            if sig:
                active = {"side": sig.side, "entry": sig.entry, "sl": sig.sl,
                          "tp": sig.tp, "open_ts": sig.bar_ts, "trailed": False}
                if verbose:
                    print(f"ENTER {sig.side} @{sig.entry} sl {sig.sl} tp {sig.tp} | {sig.reason}")
        else:
            c = candles[i]
            e, sl, tp = active["entry"], active["sl"], active["tp"]
            # trailing: lock profit under each new fractal once +2 up
            profit_now = (c.c - e) if active["side"] == "long" else (e - c.c)
            if profit_now >= 2.0 and not active["trailed"]:
                if active["side"] == "long":
                    lf = last_confirmed(bullish_fractals(candles[:i+1]), i)
                    if lf and lf[1] > sl:
                        sl = lf[1] - 0.4; active["trailed"] = True
                else:
                    hf = last_confirmed(bearish_fractals(candles[:i+1]), i)
                    if hf and hf[1] < sl:
                        sl = hf[1] + 0.4; active["trailed"] = True
                active["sl"] = sl
            hit_sl = (c.l <= sl) if active["side"] == "long" else (c.h >= sl)
            hit_tp = (c.h >= tp) if active["side"] == "long" else (c.l <= tp)
            result = None
            if hit_sl and hit_tp:
                result = ("sl", sl)  # conservative
            elif hit_sl:
                result = ("sl", sl)
            elif hit_tp:
                result = ("tp", tp)
            if result:
                pnl = (result[1] - e) if active["side"] == "long" else (e - result[1])
                trades.append({**active, "exit": result[1], "exit_ts": c.ts,
                               "pnl": round(pnl * DOLLARS_PER_POINT, 2),
                               "why": result[0]})
                if verbose:
                    print(f"EXIT {result[0]} @{result[1]:.1f} pnl {trades[-1]['pnl']:+.2f}")
                active = None
    return trades


if __name__ == "__main__":
    cs = fetch("GC=F", "5m", "5d")
    print(f"{len(cs)} candles")
    tr = backtest(cs, verbose="--verbose" in sys.argv)
    wins = [t for t in tr if t["pnl"] > 0]
    tot = round(sum(t["pnl"] for t in tr), 2)
    print(f"\ntrades: {len(tr)}  wins: {len(wins)}  winrate: {100*len(wins)/len(tr):.0f}% " if tr else "\ntrades: 0")
    print(f"total PnL @0.01 lot: ${tot:+.2f}")
    if tr:
        print(f"avg win: ${sum(t['pnl'] for t in wins)/len(wins):.2f}  "
              f"avg loss: ${sum(t['pnl'] for t in tr if t['pnl']<=0)/max(1,len(tr)-len(wins)):.2f}")
        print(f"best: ${max(t['pnl'] for t in tr):+.2f}  worst: ${min(t['pnl'] for t in tr):+.2f}")
