import os
import time
import math
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

RYU_FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "")
DEFAULT_ASSET = os.getenv("RYU_DEFAULT_ASSET", "EURUSD_otc")
DEFAULT_EXPIRY = int(os.getenv("RYU_EXPIRY_SECONDS", "300"))
MIN_CONFIDENCE = float(os.getenv("RYU_MIN_CONFIDENCE", "78"))

state = {
    "asset": DEFAULT_ASSET,
    "price": 0.0,
    "direction": "WAIT",
    "confidence": 0.0,
    "payout": 0.0,
    "entry_price": 0.0,
    "signal_time": None,
    "entry_deadline": None,
    "expiry_seconds": DEFAULT_EXPIRY,
    "feed_connected": False,
    "last_update": 0.0,
    "candles": [],
    "indicators": {
        "ema9": 0.0,
        "ema20": 0.0,
        "ema50": 0.0,
        "rsi": 50.0,
        "macd": 0.0,
        "cci": 0.0,
        "sar": 0.0,
        "alligator": {
            "jaw": 0.0,
            "teeth": 0.0,
            "lips": 0.0,
        },
    },
}

# ============================================================
# INDICATORS
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sma(values, period):
    if not values:
        return 0.0

    data = values[-period:]

    if not data:
        return 0.0

    return sum(data) / len(data)


def ema(values, period):
    if not values:
        return 0.0

    if len(values) < period:
        return sum(values) / len(values)

    multiplier = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = ((value - result) * multiplier) + result

    return result


def calculate_rsi(closes, period=14):
    if len(closes) < 2:
        return 50.0

    changes = []

    for i in range(1, len(closes)):
        changes.append(closes[i] - closes[i - 1])

    recent = changes[-period:]

    gains = [x for x in recent if x > 0]
    losses = [-x for x in recent if x < 0]

    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_macd(closes):
    if not closes:
        return 0.0

    fast = ema(closes, 12)
    slow = ema(closes, 26)

    return fast - slow


def calculate_cci(candles, period=20):
    if len(candles) < 2:
        return 0.0

    typical = []

    for candle in candles[-period:]:
        high = safe_float(candle.get("high"))
        low = safe_float(candle.get("low"))
        close = safe_float(candle.get("close"))

        typical.append((high + low + close) / 3.0)

    if not typical:
        return 0.0

    average = sum(typical) / len(typical)

    deviation = sum(abs(x - average) for x in typical) / len(typical)

    if deviation == 0:
        return 0.0

    return (typical[-1] - average) / (0.015 * deviation)


def calculate_indicators(candles):
    closes = [
        safe_float(c.get("close"))
        for c in candles
        if safe_float(c.get("close")) != 0
    ]

    if not closes:
        return state["indicators"]

    price = closes[-1]

    ema9 = ema(closes, 9)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    cci = calculate_cci(candles)

    # Simple SAR approximation for dashboard purposes.
    recent_lows = [
        safe_float(c.get("low"))
        for c in candles[-10:]
        if safe_float(c.get("low")) != 0
    ]

    recent_highs = [
        safe_float(c.get("high"))
        for c in candles[-10:]
        if safe_float(c.get("high")) != 0
    ]

    sar = min(recent_lows) if recent_lows else price

    if len(candles) >= 5:
        jaw = sma(closes, 13)
        teeth = sma(closes, 8)
        lips = sma(closes, 5)
    else:
        jaw = price
        teeth = price
        lips = price

    return {
        "ema9": round(ema9, 6),
        "ema20": round(ema20, 6),
        "ema50": round(ema50, 6),
        "rsi": round(rsi, 2),
        "macd": round(macd, 6),
        "cci": round(cci, 2),
        "sar": round(sar, 6),
        "alligator": {
            "jaw": round(jaw, 6),
            "teeth": round(teeth, 6),
            "lips": round(lips, 6),
        },
    }


def generate_signal(ind):
    price = state["price"]

    if price <= 0:
        return "WAIT", 0.0

    score = 0
    reasons = 0

    # EMA trend
    if ind["ema9"] > ind["ema20"]:
        score += 1
        reasons += 1
    elif ind["ema9"] < ind["ema20"]:
        score -= 1
        reasons += 1

    if ind["ema20"] > ind["ema50"]:
        score += 1
        reasons += 1
    elif ind["ema20"] < ind["ema50"]:
        score -= 1
        reasons += 1

    # RSI
    if ind["rsi"] > 55:
        score += 1
        reasons += 1
    elif ind["rsi"] < 45:
        score -= 1
        reasons += 1

    # MACD
    if ind["macd"] > 0:
        score += 1
        reasons += 1
    elif ind["macd"] < 0:
        score -= 1
        reasons += 1

    # CCI
    if ind["cci"] > 50:
        score += 1
        reasons += 1
    elif ind["cci"] < -50:
        score -= 1
        reasons += 1

    # Alligator
    lips = ind["alligator"]["lips"]
    teeth = ind["alligator"]["teeth"]
    jaw = ind["alligator"]["jaw"]

    if lips > teeth > jaw:
        score += 1
        reasons += 1
    elif lips < teeth < jaw:
        score -= 1
        reasons += 1

    if reasons == 0:
        return "WAIT", 0.0

    strength = abs(score) / reasons
    confidence = 50.0 + (strength * 45.0)

    if score > 0 and confidence >= MIN_CONFIDENCE:
        return "CALL", round(confidence, 1)

    if score < 0 and confidence >= MIN_CONFIDENCE:
        return "PUT", round(confidence, 1)

    return "WAIT", round(confidence, 1)


# ============================================================
# FEED PROCESSING
# ============================================================

def process_candles(candles, asset=None):
    cleaned = []

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        cleaned.append({
            "time": candle.get("time", time.time()),
            "open": safe_float(candle.get("open")),
            "high": safe_float(candle.get("high")),
            "low": safe_float(candle.get("low")),
            "close": safe_float(candle.get("close")),
            "volume": safe_float(candle.get("volume")),
        })

    if not cleaned:
        return False

    state["candles"] = cleaned[-250:]

    latest = state["candles"][-1]

    state["price"] = latest["close"]

    if asset:
        state["asset"] = str(asset)

    state["indicators"] = calculate_indicators(state["candles"])

    direction, confidence = generate_signal(state["indicators"])

    state["direction"] = direction
    state["confidence"] = confidence
    state["entry_price"] = state["price"]
    state["last_update"] = time.time()
    state["feed_connected"] = True

    now = time.time()

    if direction in ("CALL", "PUT"):
        state["signal_time"] = now
        state["entry_deadline"] = now + 15

    return True


# ============================================================
# DASHBOARD
# ============================================================

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>RYU V2 Signal Dashboard</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #06120b;
    color: #ffffff;
}

.header {
    padding: 18px;
    background: #0b2415;
    border-bottom: 2px solid #1d8f4b;
}

.logo {
    font-size: 28px;
    font-weight: bold;
}

.subtitle {
    color: #8bd7a7;
    margin-top: 4px;
}

.container {
    padding: 16px;
    max-width: 1200px;
    margin: auto;
}

.grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
}

.card {
    background: #0b1e12;
    border: 1px solid #1d5c37;
    border-radius: 12px;
    padding: 16px;
}

.label {
    color: #88b89b;
    font-size: 12px;
    text-transform: uppercase;
}

.value {
    font-size: 22px;
    font-weight: bold;
    margin-top: 7px;
}

.signal {
    text-align: center;
    padding: 28px;
    margin-top: 16px;
    border-radius: 16px;
    background: #0b2415;
    border: 2px solid #237c48;
}

.signal-direction {
    font-size: 48px;
    font-weight: bold;
}

.call {
    color: #4cff91;
}

.put {
    color: #ff6262;
}

.wait {
    color: #ffd966;
}

.chart {
    height: 300px;
    margin-top: 16px;
    background: #071b0e;
    border-radius: 12px;
    border: 1px solid #1d5c37;
    padding: 12px;
    overflow: hidden;
}

.chart-line {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6fa982;
}

.indicators {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-top: 16px;
}

.status {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 20px;
    background: #173c26;
    color: #67ff9d;
}

.disconnected {
    background: #421919;
    color: #ff7777;
}

@media(max-width: 800px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
    }

    .indicators {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media(max-width: 500px) {
    .grid {
        grid-template-columns: 1fr;
    }

    .indicators {
        grid-template-columns: 1fr;
    }
}
</style>
</head>

<body>

<div class="header">
    <div class="logo">🔥 RYU V2</div>
    <div class="subtitle">Signal Intelligence Dashboard</div>
</div>

<div class="container">

    <div class="grid">

        <div class="card">
            <div class="label">Asset</div>
            <div class="value" id="asset">--</div>
        </div>

        <div class="card">
            <div class="label">Price</div>
            <div class="value" id="price">--</div>
        </div>

        <div class="card">
            <div class="label">Confidence</div>
            <div class="value" id="confidence">--</div>
        </div>

        <div class="card">
            <div class="label">Feed</div>
            <div class="value">
                <span id="feed" class="status disconnected">
                    DISCONNECTED
                </span>
            </div>
        </div>

    </div>

    <div class="signal">

        <div class="label">Current Signal</div>

        <div id="direction" class="signal-direction wait">
            WAIT
        </div>

        <div>
            Entry:
            <strong id="entry">--</strong>
        </div>

        <div style="margin-top:10px">
            Entry Window:
            <strong id="countdown">--</strong>
        </div>

    </div>

    <div class="chart">
        <div class="chart-line" id="chart">
            Waiting for live candle feed...
        </div>
    </div>

    <div class="indicators">

        <div class="card">
            <div class="label">EMA 9</div>
            <div class="value" id="ema9">--</div>
        </div>

        <div class="card">
            <div class="label">EMA 20</div>
            <div class="value" id="ema20">--</div>
        </div>

        <div class="card">
            <div class="label">EMA 50</div>
            <div class="value" id="ema50">--</div>
        </div>

        <div class="card">
            <div class="label">RSI</div>
            <div class="value" id="rsi">--</div>
        </div>

        <div class="card">
            <div class="label">MACD</div>
            <div class="value" id="macd">--</div>
        </div>

        <div class="card">
            <div class="label">CCI</div>
            <div class="value" id="cci">--</div>
        </div>

        <div class="card">
            <div class="label">Parabolic SAR</div>
            <div class="value" id="sar">--</div>
        </div>

        <div class="card">
            <div class="label">Alligator Jaw</div>
            <div class="value" id="jaw">--</div>
        </div>

        <div class="card">
            <div class="label">Alligator Teeth</div>
            <div class="value" id="teeth">--</div>
        </div>

        <div class="card">
            <div class="label">Alligator Lips</div>
            <div class="value" id="lips">--</div>
        </div>

    </div>

</div>

<script>

async function updateDashboard() {

    try {

        const response = await fetch("/api/status");

        const data = await response.json();

        document.getElementById("asset").textContent =
            data.asset || "--";

        document.getElementById("price").textContent =
            data.price ? data.price : "--";

        document.getElementById("confidence").textContent =
            data.confidence + "%";

        const feed = document.getElementById("feed");

        if (data.feed_connected) {
            feed.textContent = "LIVE";
            feed.className = "status";
        } else {
            feed.textContent = "DISCONNECTED";
            feed.className = "status disconnected";
        }

        const direction = document.getElementById("direction");

        direction.textContent = data.direction;

        direction.className =
            "signal-direction " +
            data.direction.toLowerCase();

        document.getElementById("entry").textContent =
            data.entry_price || "--";

        document.getElementById("ema9").textContent =
            data.indicators.ema9;

        document.getElementById("ema20").textContent =
            data.indicators.ema20;

        document.getElementById("ema50").textContent =
            data.indicators.ema50;

        document.getElementById("rsi").textContent =
            data.indicators.rsi;

        document.getElementById("macd").textContent =
            data.indicators.macd;

        document.getElementById("cci").textContent =
            data.indicators.cci;

        document.getElementById("sar").textContent =
            data.indicators.sar;

        document.getElementById("jaw").textContent =
            data.indicators.alligator.jaw;

        document.getElementById("teeth").textContent =
            data.indicators.alligator.teeth;

        document.getElementById("lips").textContent =
            data.indicators.alligator.lips;

        document.getElementById("chart").textContent =
            data.candles + " candles received";

        updateCountdown(data.entry_deadline);

    } catch (error) {

        console.log(error);

    }
}


function updateCountdown(deadline) {

    const element = document.getElementById("countdown");

    if (!deadline) {
        element.textContent = "--";
        return;
    }

    const remaining = Math.max(
        0,
        Math.ceil(deadline - Date.now() / 1000)
    );

    if (remaining <= 0) {
        element.textContent = "EXPIRED";
    } else {
        element.textContent = remaining + " seconds";
    }
}


setInterval(updateDashboard, 1000);

updateDashboard();

</script>

</body>
</html>
"""


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def dashboard():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():

    age = time.time() - state["last_update"]

    connected = (
        state["feed_connected"]
        and age < 30
    )

    return jsonify({
        "ok": True,
        "asset": state["asset"],
        "price": state["price"],
        "direction": state["direction"],
        "confidence": state["confidence"],
        "payout": state["payout"],
        "entry_price": state["entry_price"],
        "signal_time": state["signal_time"],
        "entry_deadline": state["entry_deadline"],
        "expiry_seconds": state["expiry_seconds"],
        "feed_connected": connected,
        "last_update": state["last_update"],
        "candles": len(state["candles"]),
        "indicators": state["indicators"],
    })


@app.route("/api/feed", methods=["POST"])
def api_feed():

    if RYU_FEED_TOKEN:

        supplied = request.headers.get(
            "X-RYU-TOKEN",
            ""
        )

        if supplied != RYU_FEED_TOKEN:
            return jsonify({
                "ok": False,
                "error": "unauthorized"
            }), 401

    data = request.get_json(
        silent=True
    ) or {}

    candles = data.get("candles")

    if candles is None:

        candle = data.get("candle")

        if candle:
            candles = [candle]

    if not candles:

        return jsonify({
            "ok": False,
            "error": "No candles supplied"
        }), 400

    asset = data.get(
        "asset",
        DEFAULT_ASSET
    )

    payout = safe_float(
        data.get("payout"),
        0.0
    )

    state["payout"] = payout

    success = process_candles(
        candles,
        asset
    )

    if not success:

        return jsonify({
            "ok": False,
            "error": "Invalid candle data"
        }), 400

    return jsonify({
        "ok": True,
        "asset": state["asset"],
        "price": state["price"],
        "direction": state["direction"],
        "confidence": state["confidence"],
        "entry_price": state["entry_price"],
        "entry_deadline": state["entry_deadline"],
    })


@app.route("/api/health")
def health():

    return jsonify({
        "ok": True,
        "service": "Ryu V2 Signal Dashboard",
        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })


# ============================================================
# LOCAL START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
