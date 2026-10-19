"""XAU/USD 1-minute SPOT candles via TwelveData (free tier).

API keys live in the repo-local `.env` (never committed — see .env.example):
    TWELVEDATA_KEY=<key1>
    TWELVEDATA_KEY_2=<key2>   # optional; more keys = more daily quota
    ...

Free tier = 800 calls/day/key. At 1-minute polling you need ~1,440/day, so
two keys cover a full day; one key covers ~13h. Keys rotate round-robin and
the fetcher fails over to the next key on quota (429) errors.

Key travels via `curl -K -` config on stdin, never in argv (ps-visible).
"""
import datetime
import json
import os
import subprocess
from kfa_engine import Candle

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env")
ROTATION_FILE = os.path.join(HERE, ".key_rotation")


def _load_env(path=ENV_FILE):
    vals = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return vals


def _twelvedata_keys():
    """All TwelveData keys from .env. Never logged."""
    env = _load_env()
    keys = []
    for k in sorted(env, key=lambda x: (len(x), x)):
        if k.startswith("TWELVEDATA_KEY") and env[k] and env[k] not in keys:
            keys.append(env[k])
    return keys


def _key_offset(n):
    """Round-robin start index persisted across runs, so consecutive polls
    spread evenly over the keys instead of hammering key #1 first."""
    try:
        i = int(open(ROTATION_FILE).read().strip())
    except Exception:
        i = 0
    try:
        with open(ROTATION_FILE, "w") as f:
            f.write(str((i + 1) % n))
    except Exception:
        pass
    return i % n


def fetch_spot_1m(outputsize=250):
    """TwelveData XAU/USD 1-minute SPOT candles, oldest-first.

    Raises RuntimeError only when every key fails — callers stay silent and
    retry next run rather than spamming alerts.
    """
    keys = _twelvedata_keys()
    if not keys:
        raise RuntimeError("TwelveData key missing — copy .env.example to .env and add TWELVEDATA_KEY")
    order = [(_key_offset(len(keys)) + j) % len(keys) for j in range(len(keys))]
    last_err = None
    for ki in order:
        key = keys[ki]
        url = ("https://api.twelvedata.com/time_series?symbol=XAU/USD"
               f"&interval=1min&outputsize={outputsize}&timezone=UTC&apikey={key}")
        cfg = f'url = "{url}"\n'
        out = subprocess.run(
            ["curl", "-s", "-m", "30", "-K", "-",
             "--retry", "2", "--retry-delay", "2"],
            input=cfg, capture_output=True, text=True)
        try:
            d = json.loads(out.stdout)
        except Exception:
            last_err = f"twelvedata: bad response: {out.stdout[:120]!r}"
            continue  # next key
        if d.get("status") == "error" or "values" not in d:
            last_err = f"twelvedata: {str(d)[:150]}"
            continue  # quota/dead key -> try next
        candles = []
        for v in reversed(d["values"]):
            try:
                ts = int(datetime.datetime.strptime(
                    v["datetime"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=datetime.timezone.utc).timestamp())
                candles.append(Candle(ts, float(v["open"]), float(v["high"]),
                                      float(v["low"]), float(v["close"])))
            except (KeyError, ValueError, TypeError):
                continue
        if not candles:
            last_err = "twelvedata: no candles parsed"
            continue
        return candles
    raise RuntimeError(last_err or "twelvedata: all keys failed")


if __name__ == "__main__":
    cs = fetch_spot_1m(5)
    print(f"fetched {len(cs)} candles, last close {cs[-1].c:.1f}")
