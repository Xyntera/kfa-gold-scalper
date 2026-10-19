"""
KFA EMA Scalping strategy engine (XAUUSD / gold).
Mechanical implementation of the EMA 9/14/30 scalping method:
  EMA cross direction -> pullback tap of EMA 9 + decisive rejection candle ->
  break of the rejection extreme. SL beyond EMA 30 (+buffer), TP = 1:1 vs SL.
Skip rules: no first-push chase (3 bars after cross), no unbroken-high
rejection, CHOCH flip voids the side, chop guard (9/30 separation >= $0.50).
Pure functions over OHLC candle lists. No I/O here.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import datetime


def _ist(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts + 19800, datetime.timezone.utc).strftime("%H:%M")

EMA_FAST, EMA_MID, EMA_SLOW = 9, 14, 30
SL_BUFFER = 0.40        # $ buffer beyond the 30 EMA for the stop
FRACTAL_LAG = 2         # fractal needs 2 bars on each side -> confirmed with lag
MIN_BARS_AFTER_CROSS = 3  # no entry on the first push right after a cross
MIN_EMA_SEP = 0.50      # $ chop guard (KFA #4: never trade sideways): 9/30 must be this far apart
DOLLARS_PER_POINT = 1.0   # 0.01 lot forex gold convention: $1 per $1 move


def ema(values: List[float], n: int) -> List[float]:
    k = 2.0 / (n + 1)
    out, prev = [], values[0]
    for v in values:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


@dataclass
class Candle:
    ts: int
    o: float
    h: float
    l: float
    c: float


@dataclass
class Signal:
    side: str            # 'long' or 'short'
    entry: float
    sl: float
    tp: float
    reason: str
    bar_ts: int


def bearish_fractals(candles: List[Candle]) -> Dict[int, float]:
    """index -> high, confirmed (needs FRACTAL_LAG bars after)."""
    fr = {}
    hs = [c.h for c in candles]
    for i in range(2, len(hs) - FRACTAL_LAG):
        if hs[i] == max(hs[i-2:i+3]):
            fr[i] = hs[i]
    return fr


def bullish_fractals(candles: List[Candle]) -> Dict[int, float]:
    fr = {}
    ls = [c.l for c in candles]
    for i in range(2, len(ls) - FRACTAL_LAG):
        if ls[i] == min(ls[i-2:i+3]):
            fr[i] = ls[i]
    return fr


def last_confirmed(fr: Dict[int, float], upto_idx: int) -> Optional[tuple]:
    cands = [(i, v) for i, v in fr.items() if i <= upto_idx]
    return max(cands, key=lambda x: x[0]) if cands else None


@dataclass
class EngineState:
    closes: List[float] = field(default_factory=list)
    highs: List[float] = field(default_factory=list)
    lows: List[float] = field(default_factory=list)
    opens: List[float] = field(default_factory=list)
    ts: List[int] = field(default_factory=list)
    last_cross_idx: Optional[int] = None
    last_cross_dir: Optional[str] = None   # 'up' or 'down'


def _crosses(e9: List[float], e30: List[float]) -> List[tuple]:
    out = []
    for i in range(1, len(e9)):
        d_prev, d_now = e9[i-1] - e30[i-1], e9[i] - e30[i]
        if d_prev <= 0 < d_now:
            out.append((i, 'up'))
        elif d_prev >= 0 > d_now:
            out.append((i, 'down'))
    return out


_STRICT_FILTERS = ("stack", "decisive", "rr")


def _strict_on(strict, name: str) -> bool:
    """strict=True -> all filters; strict=False/None -> none;
    strict={"stack","decisive","rr"} subset -> only those."""
    if strict is True:
        return True
    if not strict:
        return False
    return name in strict


def evaluate(candles: List[Candle], strict=False) -> Optional[Signal]:
    """
    Evaluate the latest CLOSED candle. Returns a Signal or None.
    Implements the 5-question entry test from the KFA method.
    strict=True adds all high-conviction filters ("sure shot" mode);
    a subset like {"stack", "rr"} enables only those:
      - "stack": full EMA stack alignment (9>14>30 for longs, mirrored for shorts)
      - "decisive": decisive rejection candle (body >= 50% of the candle range)
      - "rr": minimum 1.0 reward:risk on the fractal TP vs the 30-EMA SL
    """
    n = len(candles)
    if n < EMA_SLOW + 10:
        return None
    i = n - 1  # signal bar (latest closed)
    closes = [c.c for c in candles]
    e9 = ema(closes, EMA_FAST)
    e14 = ema(closes, EMA_MID)
    e30 = ema(closes, EMA_SLOW)

    # Q1: direction from the most recent EMA 9/30 cross
    cross_list = _crosses(e9[:i+1], e30[:i+1])
    if not cross_list:
        return None
    cross_idx, direction = cross_list[-1]

    # Q2: not the first push — require some bars since the cross
    if i - cross_idx < MIN_BARS_AFTER_CROSS:
        return None

    # Chop guard (KFA #4: never trade sideways): EMA 9 and 30 must be
    # separated — flat/tangled EMAs mean no trade, however the candle looks.
    if abs(e9[i] - e30[i]) < MIN_EMA_SEP:
        return None

    bfr = bearish_fractals(candles)
    bfl = bullish_fractals(candles)
    c = candles[i]

    if direction == 'up':
        # CHOCH: a higher low broken -> trend may be flipping, no longs
        lf = last_confirmed(bfl, i)
        if lf and c.c < lf[1]:
            return None
        # Q3: pullback tapped the 9 EMA and rejected (green bounce)
        tapped = c.l <= e9[i] * 1.0002
        bounced = c.c > e9[i] and c.c > c.o
        if not (tapped and bounced):
            return None
        # Q4: the recent high was actually broken (no fake rejection)
        hf = last_confirmed(bfr, i)
        if hf is None:
            return None
        # the push high after the cross must exceed the prior fractal high
        push_high = max(cd.h for cd in candles[cross_idx:i+1])
        if push_high <= hf[1] + 1e-9:
            return None
        entry = c.c
        sl = min(e30[i], min(cd.l for cd in candles[max(0, i-3):i+1])) - SL_BUFFER
        tp = entry + (entry - sl)  # 2026-10-19: Glaqz's 1:1 rule — TP mirrors SL distance
        if tp <= entry:
            tp = entry + 2.0  # 1m-style fallback target
        if _strict_on(strict, "stack"):
            if not (e9[i] > e14[i] > e30[i]):
                return None                       # EMAs not stacked: weak trend
        if _strict_on(strict, "decisive"):
            rng = c.h - c.l
            if rng <= 0 or (c.c - c.o) / rng < 0.5:
                return None                       # indecisive bounce candle
        if _strict_on(strict, "rr"):
            if (tp - entry) < (entry - sl):
                return None                       # reward smaller than risk
        return Signal('long', round(entry, 2), round(sl, 2), round(tp, 2),
                      f"cross up @{_ist(candles[cross_idx].ts)}, pullback tap 9, bounce, high {hf[1]:.1f} broken",
                      c.ts)
    else:
        lf = last_confirmed(bfl, i)
        if lf is None:
            return None
        # CHOCH mirror: lower high broken -> no shorts
        hf = last_confirmed(bfr, i)
        if hf and c.c > hf[1]:
            return None
        # Q3 mirror: rally into the MA and rejection (red candle)
        tapped = c.h >= e9[i] * 0.9998
        rejected = c.c < e9[i] and c.c < c.o
        if not (tapped and rejected):
            return None
        # Q4 mirror: recent low actually broken
        push_low = min(cd.l for cd in candles[cross_idx:i+1])
        if push_low >= lf[1] - 1e-9:
            return None
        entry = c.c
        sl = max(e30[i], max(cd.h for cd in candles[max(0, i-3):i+1])) + SL_BUFFER
        tp = entry - (sl - entry)  # 2026-10-19: Glaqz's 1:1 rule — TP mirrors SL distance
        if tp >= entry:
            tp = entry - 2.0
        if _strict_on(strict, "stack"):
            if not (e9[i] < e14[i] < e30[i]):
                return None                       # EMAs not stacked: weak trend
        if _strict_on(strict, "decisive"):
            rng = c.h - c.l
            if rng <= 0 or (c.o - c.c) / rng < 0.5:
                return None                       # indecisive rejection candle
        if _strict_on(strict, "rr"):
            if (entry - tp) < (sl - entry):
                return None                       # reward smaller than risk
        return Signal('short', round(entry, 2), round(sl, 2), round(tp, 2),
                      f"cross down @{_ist(candles[cross_idx].ts)}, rally reject MA, low {lf[1]:.1f} broken",
                      c.ts)
