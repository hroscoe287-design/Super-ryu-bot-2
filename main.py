from flask import Flask, request, jsonify, render_template_string
import os
import time
import math

app = Flask(__name__)

# ============================================================
# RYU V2 SIGNAL DASHBOARD
# Signal-only dashboard — NO automatic trade placement
# ============================================================

FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "")
DEFAULT_ASSET = os.getenv("RYU_DEFAULT_ASSET", "EURUSD_otc")
EXPIRY_SECONDS = int(os.getenv("RYU_EXPIRY_SECONDS", "300"))
MIN_CONFIDENCE = float(os.getenv("RYU_MIN_CONFIDENCE", "78"))

STATE = {
    "asset": DEFAULT_ASSET,
    "price": None,
    "signal": "WAIT",
    "confidence": 0,
    "entry": None,
    "entry_window": 0,
    "expiry_seconds": EXPIRY_SECONDS,
    "feed": "DISCONNECTED",
    "last_update": 0,
    "candles": 0,
    "open": None,
    "high": None,
    "low": None,
    "close": None,
    "payout": 0,
    "message": "Waiting for Pocket Option feed..."
}

# ============================================================
# SIMPLE MARKET STATE
# ============================================================

PRICE_HISTORY = {}
CANDLE_HISTORY = {}


def clean_number(value):
    try:
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None


def calculate_signal(asset):
    """
    Signal engine for dashboard display.

    This is intentionally conservative:
    insufficient data = WAIT.
    """

    prices = PRICE_HISTORY.get(asset, [])

    if len(prices) < 20:
        return "WAIT", 0

    recent = prices[-20:]

    # Short and long averages
    short = sum(recent[-5:]) / 5
    long = sum(recent[-20:]) / 20

    # Recent momentum
    momentum = recent[-1] - recent[-6]

    if long == 0:
        return "WAIT", 0

    distance = abs(short - long) / abs(long) * 100000

    confidence = 50

    if short > long:
        confidence += min(25, distance * 2)

    elif short < long:
        confidence += min(25, distance * 2)

    if momentum > 0:
        confidence += 15

    elif momentum < 0:
        confidence += 15

    confidence = max(0, min(99, round(confidence)))

    if short > long and momentum > 0 and confidence >= MIN_CONFIDENCE:
        return "CALL", confidence

    if short < long and momentum < 0 and confidence >= MIN_CONFIDENCE:
        return "PUT", confidence

    return "WAIT", confidence


def process_price(asset, price):
    if not asset or price is None:
        return

    if asset not in PRICE_HISTORY:
        PRICE_HISTORY[asset] = []

    PRICE_HISTORY[asset].append(price)

    # Keep memory small
    PRICE_HISTORY[asset] = PRICE_HISTORY[asset][-200:]

    signal, confidence = calculate_signal(asset)

    STATE["signal"] = signal
    STATE["confidence"] = confidence

    if signal in ("CALL", "PUT"):
        STATE["entry"] = price
        STATE["entry_window"] = 12
        STATE["message"] = "ENTRY WINDOW ACTIVE"
    else:
        STATE["message"] = "Waiting for high-confidence setup..."


# ============================================================
# AUTHENTICATION
# ============================================================

def authorized(req):
    """
    If RYU_FEED_TOKEN is configured, require it.

    Accepted:
      Authorization: Bearer YOUR_TOKEN
    OR
      X-RYU-TOKEN: YOUR_TOKEN
    """

    if not FEED_TOKEN:
        return True

    auth = req.headers.get("Authorization", "")

    if auth.startswith("Bearer "):
        token = auth[7:].strip()

        if token == FEED_TOKEN:
            return True

    header_token = req.headers.get("X-RYU-TOKEN", "")

    if header_token == FEED_TOKEN:
        return True

    # Also allow token in JSON body
    try:
        body = req.get_json(silent=True) or {}

        if body.get("token") == FEED_TOKEN:
            return True
    except Exception:
        pass

    return False


# ============================================================
# HOME / DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>RYU V2 Signal Dashboard</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #06110b;
    color: white;
    font-family: Arial, Helvetica, sans-serif;
}

.header {
    padding: 18px;
    background: linear-gradient(90deg,#07150c,#0d2a17,#07150c);
    border-bottom: 2px solid #19ff72;
    text-align: center;
}

.logo {
    font-size: 30px;
    font-weight: 900;
    color: #19ff72;
    letter-spacing: 3px;
}

.subtitle {
    color: #9affba;
    font-size: 12px;
    margin-top: 5px;
    letter-spacing: 2px;
}

.statusbar {
    display: flex;
    gap: 10px;
    padding: 12px;
    overflow-x: auto;
    background: #08170d;
}

.status {
    min-width: 130px;
    padding: 10px;
    border: 1px solid #174d2b;
    border-radius: 8px;
    background: #0b2113;
}

.status-title {
    color: #80a88d;
    font-size: 11px;
}

.status-value {
    font-size: 16px;
    font-weight: bold;
    margin-top: 4px;
}

.live {
    color: #19ff72;
}

.dead {
    color: #ff4d4d;
}

.container {
    max-width: 1100px;
    margin: auto;
    padding: 15px;
}

.card {
    background: linear-gradient(145deg,#0b2113,#07150c);
    border: 1px solid #19562f;
    border-radius: 14px;
    padding: 18px;
    margin-bottom: 15px;
    box-shadow: 0 0 25px rgba(0,255,100,.06);
}

.asset {
    color: #9affba;
    font-size: 14px;
}

.price {
    font-size: 38px;
    font-weight: 900;
    margin-top: 8px;
}

.signal-box {
    text-align: center;
    padding: 25px;
    border-radius: 12px;
    background: #061
