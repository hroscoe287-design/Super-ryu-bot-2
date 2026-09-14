import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))
FEED_TOKEN = os.environ.get("RYU_FEED_TOKEN", "change-me")
DEFAULT_ASSET = os.environ.get("RYU_DEFAULT_ASSET", "EURUSD_otc")
EXPIRY_SECONDS = int(os.environ.get("RYU_EXPIRY_SECONDS", "300"))
MIN_CONFIDENCE = float(os.environ.get("RYU_MIN_CONFIDENCE", "78"))

# ============================================================
# STATE
# ============================================================

state = {
    "asset": DEFAULT_ASSET,
    "price": 0.0,
    "previous_price": 0.0,
    "signal": "WAIT",
    "confidence": 0,
    "entry_price": 0.0,
    "entry_time": None,
    "expiry_seconds": EXPIRY_SECONDS,
    "signal_time": None,
    "feed_time": None,
    "feed_status": "WAITING FOR FEED",
    "scan": 0,
    "candles": [],
    "indicators": {
        "ema9": 0,
        "ema20": 0,
        "ema50": 0,
        "bb_upper": 0,
        "bb_middle": 0,
        "bb_lower": 0,
        "supertrend": 0,
        "supertrend_direction": "WAIT",
    },
}


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def calculate_ema(values, period):
    if not values:
        return 0.0

    if len(values) < period:
        return sum(values) / len(values)

    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calculate_bollinger(values, period=20, deviations=2):
    if not values:
        return 0.0, 0.0, 0.0

    data = values[-period:]

    middle = sum(data) / len(data)

    variance = sum((x - middle) ** 2 for x in data) / len(data)
    std = variance ** 0.5

    upper = middle + deviations * std
    lower = middle - deviations * std

    return upper, middle, lower


def calculate_supertrend(values, period=10, multiplier=3):
    """
    Simplified price-based Supertrend.

    This is intended for the dashboard signal engine.
    For exact broker OHLC Supertrend calculations, provide
    candle high/low/close data through /api/feed.
    """

    if len(values) < 2:
        return 0.0, "WAIT"

    recent = values[-period:] if len(values) >= period else values

    average = sum(recent) / len(recent)

    volatility = 0.0
    if len(recent) > 1:
        changes = [
            abs(recent[i] - recent[i - 1])
            for i in range(1, len(recent))
        ]
        volatility = sum(changes) / len(changes)

    band = volatility * multiplier

    upper = average + band
    lower = average - band

    price = values[-1]

    if price > upper:
        direction = "CALL"
    elif price < lower:
        direction = "PUT"
    else:
        direction = "WAIT"

    return average, direction


def calculate_signal(values):
    if len(values) < 5:
        return "WAIT", 0

    price = values[-1]

    ema9 = calculate_ema(values, 9)
    ema20 = calculate_ema(values, 20)
    ema50 = calculate_ema(values, 50)

    bb_upper, bb_middle, bb_lower = calculate_bollinger(
        values, 20, 2
    )

    supertrend, st_direction = calculate_supertrend(
        values, 10, 3
    )

    call_score = 0
    put_score = 0

    # --------------------------------------------------------
    # EMA TREND
    # --------------------------------------------------------

    if ema9 > ema20:
        call_score += 20
    elif ema9 < ema20:
        put_score += 20

    if ema20 > ema50:
        call_score += 15
    elif ema20 < ema50:
        put_score += 15

    # --------------------------------------------------------
    # PRICE VS EMA
    # --------------------------------------------------------

    if price > ema9:
        call_score += 10
    elif price < ema9:
        put_score += 10

    # --------------------------------------------------------
    # BOLLINGER
    # --------------------------------------------------------

    if price > bb_middle:
        call_score += 10
    elif price < bb_middle:
        put_score += 10

    # Avoid chasing extreme upper/lower band moves.
    if bb_upper > bb_lower:
        if price >= bb_upper:
            put_score += 5
        elif price <= bb_lower:
            call_score += 5

    # --------------------------------------------------------
    # SUPERTREND
    # --------------------------------------------------------

    if st_direction == "CALL":
        call_score += 20
    elif st_direction == "PUT":
        put_score += 20

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if len(values) >= 4:
        momentum = values[-1] - values[-4]

        if momentum > 0:
            call_score += 10
        elif momentum < 0:
            put_score += 10

    total = max(call_score, put_score)

    if call_score > put_score:
        signal = "CALL"
        confidence = total
    elif put_score > call_score:
        signal = "PUT"
        confidence = total
    else:
        signal = "WAIT"
        confidence = 0

    # Require minimum confidence.
    if confidence < MIN_CONFIDENCE:
        signal = "WAIT"

    return signal, min(99, confidence)


def update_indicators():

    values = state["candles"]

    if not values:
        return

    ema9 = calculate_ema(values, 9)
    ema20 = calculate_ema(values, 20)
    ema50 = calculate_ema(values, 50)

    bb_upper, bb_middle, bb_lower = calculate_bollinger(
        values,
        20,
        2
    )

    supertrend, st_direction = calculate_supertrend(
        values,
        10,
        3
    )

    state["indicators"] = {
        "ema9": round(ema9, 8),
        "ema20": round(ema20, 8),
        "ema50": round(ema50, 8),
        "bb_upper": round(bb_upper, 8),
        "bb_middle": round(bb_middle, 8),
        "bb_lower": round(bb_lower, 8),
        "supertrend": round(supertrend, 8),
        "supertrend_direction": st_direction,
    }


def process_price(price):

    try:
        price = float(price)
    except Exception:
        return

    if price <= 0:
        return

    state["previous_price"] = state["price"]
    state["price"] = price

    state["candles"].append(price)

    # Keep memory manageable.
    if len(state["candles"]) > 500:
        state["candles"] = state["candles"][-500:]

    state["feed_time"] = now_iso()
    state["feed_status"] = "LIVE"
    state["scan"] += 1

    update_indicators()

    signal, confidence = calculate_signal(
        state["candles"]
    )

    # New signal only when a valid signal appears.
    if signal in ("CALL", "PUT"):

        state["signal"] = signal
        state["confidence"] = confidence
        state["entry_price"] = price
        state["entry_time"] = time.time()
        state["signal_time"] = now_iso()

    else:
        # Keep current signal while its entry window is alive.
        if state["entry_time"] is None:
            state["signal"] = "WAIT"
            state["confidence"] = confidence


# ============================================================
# FEED HEALTH
# ============================================================

def feed_monitor():

    while True:

        try:
            if state["feed_time"]:

                last = datetime.fromisoformat(
                    state["feed_time"]
                )

                age = (
                    datetime.now(timezone.utc) - last
                ).total_seconds()

                if age > 15:
                    state["feed_status"] = "STALE"

            time.sleep(3)

        except Exception:
            time.sleep(3)


threading.Thread(
    target=feed_monitor,
    daemon=True
).start()


# ============================================================
# API
# ============================================================

@app.route("/api/status")
def api_status():

    entry_remaining = 0

    if state["entry_time"]:

        elapsed = time.time() - state["entry_time"]

        entry_remaining = max(
            0,
            int(15 - elapsed)
        )

        if entry_remaining == 0:
            state["signal"] = "WAIT"
            state["confidence"] = 0
            state["entry_time"] = None

    return jsonify({
        "ok": True,
        "asset": state["asset"],
        "price": state["price"],
        "signal": state["signal"],
        "confidence": state["confidence"],
        "entry_price": state["entry_price"],
        "entry_remaining": entry_remaining,
        "expiry_seconds": state["expiry_seconds"],
        "signal_time": state["signal_time"],
        "feed_time": state["feed_time"],
        "feed_status": state["feed_status"],
        "scan": state["scan"],
        "indicators": state["indicators"],
        "candles": state["candles"][-100:],
    })


@app.route("/api/feed", methods=["POST"])
def api_feed():

    # Token authentication.
    token = request.headers.get("X-RYU-T
