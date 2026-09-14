Yes. This version is designed so no Pocket Option SSID is required. It receives screenshots/frames from your Android screen-feed and analyzes the visible chart.
Important: this does not connect to Pocket Option's private API. It only analyzes what is visible on the screen. Because the chart image doesn't expose a guaranteed machine-readable price scale, the displayed visual price is a normalized chart value unless your feed also sends the actual price.
Replace your entire main.py with this:
import os
import io
import time
import base64
import threading
from datetime import datetime

import numpy as np
from flask import Flask, request, jsonify, render_template_string
from PIL import Image

app = Flask(__name__)

# ============================================================
# RYU V2 - SCREEN FEED SIGNAL ENGINE
# No SSID required
# ============================================================

ASSET = os.getenv("RYU_DEFAULT_ASSET", "EURUSD_otc")
EXPIRY_SECONDS = int(os.getenv("RYU_EXPIRY_SECONDS", "300"))
MIN_CONFIDENCE = float(os.getenv("RYU_MIN_CONFIDENCE", "78"))

state = {
    "asset": ASSET,
    "price": None,
    "confidence": 0,
    "feed": "DISCONNECTED",
    "signal": "WAIT",
    "entry": None,
    "entry_window": None,
    "candles": [],
    "candle_count": 0,
    "last_frame": 0,
    "last_update": None,
    "frame_count": 0,
    "ema9": 0,
    "ema20": 0,
    "ema50": 0,
    "rsi": 50,
    "macd": 0,
    "cci": 0,
    "sar": 0,
    "jaw": 0,
    "teeth": 0,
    "lips": 0,
    "screen_width": 0,
    "screen_height": 0,
    "message": "Waiting for Android screen feed..."
}

lock = threading.Lock()


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) == 0:
        return 0.0

    alpha = 2.0 / (period + 1.0)
    result = float(values[0])

    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result

    return result


def rsi(values, period=14):
    if len(values) < 2:
        return 50.0

    values = np.asarray(values, dtype=float)
    delta = np.diff(values)

    gains = np.maximum(delta, 0)
    losses = np.maximum(-delta, 0)

    if len(gains) < period:
        period = len(gains)

    if period <= 0:
        return 50.0

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def macd(values):
    if len(values) < 5:
        return 0.0

    fast = ema(values, 12)
    slow = ema(values, 26)

    return float(fast - slow)


def cci(candles, period=20):
    if len(candles) < 3:
        return 0.0

    recent = candles[-period:]

    typical = np.array([
        (c["high"] + c["low"] + c["close"]) / 3
        for c in recent
    ], dtype=float)

    mean = np.mean(typical)
    deviation = np.mean(np.abs(typical - mean))

    if deviation == 0:
        return 0.0

    current = typical[-1]

    return float((current - mean) / (0.015 * deviation))


def alligator(candles):
    if not candles:
        return 0.0, 0.0, 0.0

    closes = np.array(
        [c["close"] for c in candles],
        dtype=float
    )

    # Smoothed approximation of Alligator lines.
    jaw = ema(closes, 13)
    teeth = ema(closes, 8)
    lips = ema(closes, 5)

    return float(jaw), float(teeth), float(lips)


def parabolic_sar(candles, step=0.02, maximum=0.2):
    if len(candles) < 3:
        return candles[-1]["close"] if candles else 0.0

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    rising = True
    sar = lows[0]
    extreme = highs[0]
    acceleration = step

    for i in range(1, len(candles)):
        high = highs[i]
        low = lows[i]

        sar = sar + acceleration * (extreme - sar)

        if rising:
            if i >= 2:
                sar = min(sar, lows[i - 1], lows[i - 2])
            else:
                sar = min(sar, lows[i - 1])

            if low < sar:
                rising = False
                sar = extreme
                extreme = low
                acceleration = step
            elif high > extreme:
                extreme = high
                acceleration = min(acceleration + step, maximum)

        else:
            if i >= 2:
                sar = max(sar, highs[i - 1], highs[i - 2])
            else:
                sar = max(sar, highs[i - 1])

            if high > sar:
                rising = True
                sar = extreme
                extreme = high
                acceleration = step
            elif low < extreme:
                extreme = low
                acceleration = min(acceleration + step, maximum)

    return float(sar)


# ============================================================
# SCREEN IMAGE PROCESSING
# ============================================================

def decode_image(raw):
    try:
        if isinstance(raw, bytes):
            return Image.open(io.BytesIO(raw)).convert("RGB")

        if isinstance(raw, str):
            if "," in raw:
                raw = raw.split(",", 1)[1]

            data = base64.b64decode(raw)
            return Image.open(io.BytesIO(data)).convert("RGB")

    except Exception:
        return None

    return None


def detect_chart_candles(image):
    """
    Attempts to identify green/red candlesticks directly
    from the visible Android chart.

    This is visual analysis only.
    It does not connect to Pocket Option.
    """

    img = image.copy()

    # Resize to a manageable working resolution.
    max_width = 1000

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize(
            (max_width, int(img.height * ratio))
        )

    arr = np.asarray(img)

    height, width, _ = arr.shape

    # Ignore top/bottom UI areas.
    y1 = int(height * 0.15)
    y2 = int(height * 0.88)

    chart = arr[y1:y2]

    r = chart[:, :, 0].astype(int)
    g = chart[:, :, 1].astype(int)
    b = chart[:, :, 2].astype(int)

    # Broad green candle detection.
    green = (
        (g > r * 1.12) &
        (g > b * 1.08) &
        (g > 70)
    )

    # Broad red candle detection.
    red = (
        (r > g * 1.15) &
        (r > b * 1.15) &
        (r > 70)
    )

    candle_mask = green | red

    column_strength = np.sum(candle_mask, axis=0)

    # Find columns containing enough candle pixels.
    active = column_strength > max(2, int(height * 0.015))

    groups = []

    start = None

    for x, value in enumerate(active):
        if value and start is None:
            start = x

        elif not value and start is not None:
            if x - start >= 2:
                groups.append((start, x - 1))
            start = None

    if start is not None:
        groups.append((start, width - 1))

    # Merge very close groups.
    merged = []

    for group in groups:
        if not merged:
            merged.append(list(group))
            continue

        previous = merged[-1]

        if group[0] - previous[1] <= 4:
            previous[1] = group[1]
        else:
            merged.append(list(group))

    candles = []

    # Keep the most recent visible candles.
    merged = merged[-80:]

    for x1, x2 in merged:
        section = candle_mask[:, x1:x2 + 1]

        ys, xs = np.where(section)

        if len(ys) < 3:
            continue

        top = int(np.min(ys))
        bottom = int(np.max(ys))

        center_x = (x1 + x2) // 2

        # Determine candle direction.
        green_pixels = np.sum(green[:, x1:x2 + 1])
        red_pixels = np.sum(red[:, x1:x2 + 1])

        bullish = green_pixels >= red_pixels

        # Visual coordinate becomes normalized market value.
        visual_close = float(height - np.mean(ys))

        candle = {
            "open": visual_close - 1.0 if bullish else visual_close + 1.0,
            "high": float(height - top),
            "low": float(height - bottom),
            "close": visual_close,
            "bullish": bool(bullish),
            "x": center_x
        }

        candles.append(candle)

    return candles


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(candles):
    if len(candles) < 10:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "reason": "Waiting for more visible candles"
        }

    closes = np.array(
        [c["close"] for c in candles],
        dtype=float
    )

    ema9_value = ema(closes, 9)
    ema20_value = ema(closes, 20)
    ema50_value = ema(closes, 50)

    rsi_value = rsi(closes)
    macd_value = macd(closes)
    cci_value = cci(candles)

    sar_value = parabolic_sar(candles)

    jaw, teeth, lips = alligator(candles)

    current = closes[-1]

    score_call = 0
    score_put = 0

    # EMA trend.
    if ema9_value > ema20_value:
        score_call += 15
    elif ema9_value < ema20_value:
        score_put += 15

    if ema20_value > ema50_value:
        score_call += 15
    elif ema20_value < ema50_value:
        score_put += 15

    # RSI.
    if 50 < rsi_value < 70:
        score_call += 10
    elif 30 < rsi_value < 50:
        score_put += 10

    # MACD.
    if macd_value > 0:
        score_call += 10
    elif macd_value < 0:
        score_put += 10

    # CCI.
    if cci_value > 0:
        score_call += 10
    elif cci_value < 0:
        score_put += 10

    # SAR.
    if current > sar_value:
        score_call += 10
    elif current < sar_value:
        score_put += 10

    # Alligator.
    if lips > teeth > jaw:
        score_call += 15
    elif lips < teeth < jaw:
        score_put += 15

    # Recent candle momentum.
    if len(closes) >= 5:
        momentum = closes[-1] - closes[-5]

        if momentum > 0:
            score_call += 10
        elif momentum < 0:
            score_put += 10

    total = score_call + score_put

    if total == 0:
        confidence = 0
        signal = "WAIT"
    else:
        winning_score = max(score_call, score_put)

        # Confidence reflects agreement between indicators.
        confidence = int(
            min(
                99,
                50 + (winning_score / 100) * 49
            )
        )

        if score_call > score_put and confidence >= MIN_CONFIDENCE:
            signal = "CALL"
        elif score_put > score_call and confidence >= MIN_CONFIDENCE:
            signal = "PUT"
        else:
            signal = "WAIT"

    return {
        "signal": signal,
        "confidence": confidence,
        "ema9": ema9_value,
        "ema20": ema20_value,
        "ema50": ema50_value,
        "rsi": rsi_value,
        "macd": macd_value,
        "cci": cci_value,
        "sar": sar_value,
        "jaw": jaw,
        "teeth": teeth,
        "lips": lips,
        "reason": f"CALL score {score_call} / PUT score {score_put}"
    }


def process_candles(candles):
    result = calculate_signal(candles)

    with lock:
        state["candles"] = candles
        state["candle_count"] = len(candles)

        state["ema9"] = round(result.get("ema9", 0), 4)
        state["ema20"] = round(result.get("ema20", 0), 4)
        state["ema50"] = round(result.get("ema50", 0), 4)

        state["rsi"] = round(result.get("rsi", 50), 2)
        state["macd"] = round(result.get("macd", 0), 4)
        state["cci"] = round(result.get("cci", 0), 2)
        state["sar"] = round(result.get("sar", 0), 4)

        state["jaw"] = round(result.get("jaw", 0), 4)
        state["teeth"] = round(result.get("teeth", 0), 4)
        state["lips"] = round(result.get("lips", 0), 4)

        if candles:
            state["price"] = round(candles[-1]["close"], 4)

        state["signal"] = result["signal"]
        state["confidence"] = result["confidence"]

        if result["signal"] in ("CALL", "PUT"):
            state["entry"] = state["price"]
            state["entry_window"] = 15
        else:
            state["entry"] = None
            state["entry_window"] = None

        state["message"] = result["reason"]


# ============================================================
# API - SCREEN FEED
# ============================================================

@app.route("/api/screen", methods=["POST"])
def receive_screen():
    """
    Accepts:

    1. Raw JPEG/PNG body
       Content-Type: image/jpeg

    OR

    2. JSON:
       {
          "image": "base64..."
       }

    Optional:
       {
          "asset": "EURUSD_otc",
          "image": "base64..."
       }
    """

    image = None
    asset = None

    content_type = request.content_type or ""

    if "application/json" in content_type:
        data = request.get_json(silent=True) or {}

        encoded = data.get("image")

        if encoded:
            image = decode_image(encoded)

        asset = data.get("asset")

    else:
        raw = request.get_data()

        if raw:
            image = decode_image(raw)

    if image is None:
        return jsonify({
            "ok": False,
            "error": "No valid image received"
        }), 400

    if asset:
        with lock:
            state["asset"] = str(asset)

    candles = detect_chart_candles(image)

    with lock:
        state["feed"] = "LIVE"
        state["last_frame"] = time.time()
        state["last_update"] = datetime.utcnow().isoformat() + "Z"
        state["frame_count"] += 1
        state["screen_width"] = image.width
        state["screen_height"] = image.height

    if candles:
        process_candles(candles)

    else:
        with lock:
            state["message"] = (
                "Screen connected, but chart candles were not detected"
            )

    return jsonify({
        "ok": True,
        "feed": "LIVE",
        "candles_detected": len(candles),
        "signal": state["signal"],
        "confidence": state["confidence"]
    })


# ============================================================
# API - OPTIONAL MANUAL CANDLE FEED
# ============================================================

@app.route("/api/feed", methods=["POST"])
def receive_feed():
    """
    Optional structured candle endpoint.

    This is useful if your Android bridge eventually extracts
    OHLC candles itself.

    JSON:
    {
      "asset": "EURUSD_otc",
      "candles": [
        {
          "open": 1,
          "high": 2,
          "low": 0,
          "close": 1.5
        }
      ]
    }
    """

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "ok": False,
            "error": "JSON body required"
        }), 400

    candles = data.get("candles", [])

    if not isinstance(candles, list):
        return jsonify({
            "ok": False,
            "error": "candles must be a list"
        }), 400

    cleaned = []

    for candle in candles[-100:]:
        try:
            cleaned.append({
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "bullish": float(candle["close"]) >= float(candle["open"])
            })
        except Exception:
            continue

    with lock:
        if data.get("asset"):
            state["asset"] = str(data["asset"])

        state["feed"] = "LIVE"
        state["last_frame"] = time.time()
        state["last_update"] = datetime.utcnow().isoformat() + "Z"
        state["frame_count"] += 1

    if cleaned:
        process_candles(cleaned)

    return jsonify({
        "ok": True,
        "candles": len(cleaned),
        "signal": state["signal"],
        "confidence": state["confidence"]
    })


# ============================================================
# API - STATE
# ============================================================

@app.route("/api/state")
def api_state():
    with lock:
        result = dict(state)

    # Don't send all candle internals to dashboard.
    result["candles"] = result["candles"][-60:]

    # Feed timeout.
    if time.time() - result["last_frame"] > 8:
        result["feed"] = "DISCONNECTED"

    return jsonify(result)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "RYU V2",
        "screen_feed": True,
        "ssid_required": False
    })


# ============================================================
# DASHBOARD
# ============================================================

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>RYU V2 Signal Intelligence</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top, #14351e 0%, #061008 55%, #020403 100%);
    color: #eaffef;
    font-family: Arial, sans-serif;
}

header {
    padding: 18px;
    border-bottom: 1px solid #234d2d;
    background: rgba(0,0,0,.55);
}

.logo {
    font-size: 27px;
    font-weight: 900;
    letter-spacing: 2px;
}

.subtitle {
    color: #8ca794;
    margin-top: 4px;
}

.container {
    padding: 14px;
    max-width: 1200px;
    margin: auto;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit,minmax(150px,1fr));
    gap: 10px;
}

.card {
    background: rgba(8,22,12,.88);
    border: 1px solid #24532e;
    border-radius: 12px;
    padding: 15px;
}

.label {
    color: #88a890;
    font-size: 12px;
    text-transform: uppercase;
}

.value {
    margin-top: 7px;
    font-size: 22px;
    font-weight: bold;
}

.signal {
    font-size: 38px;
    font-weight: 900;
}

.wait {
    color: #ffd76a;
}

.live {
    color: #69ff88;
}

.dead {
    color: #ff6666;
}

.chart {
    margin-top: 12px;
    height: 300px;
    border: 1px solid #24532e;
    border-radius: 12px;
    background:
        linear-gradient(
            rgba(50,130,70,.12) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(50,130,70,.12) 1px,
            transparent 1px
        );
    background-size: 30px 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #66816d;
}

.status {
    margin-top: 12px;
    padding: 13px;
    border-radius: 10px;
    background: #09150c;
    border: 1px solid #234d2d;
}

.small {
    font-size: 13px;
    color: #91a996;
}

.feedbox {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 7px;
    background: #777;
}

.dot.live {
    background: #55ff72;
    box-shadow: 0 0 12px #55ff72;
}

.dot.dead {
    background: #ff4444;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
}

td {
    padding: 9px;
    border-bottom: 1px solid #18351f;
}

td:last-child {
    text-align: right;
    font-weight: bold;
}
</style>
</head>

<body>

<header>
    <div class="logo">🔥 RYU V2</div>
    <div class="subtitle">
        Signal Intelligence Dashboard — Screen Feed Mode
    </div>
</header>

<div class="container">

<div class="grid">

<div class="card">
<div class="label">Asset</div>
<div class="value" id="asset">EURUSD_otc</div>
</div>

<div class="card">
<div class="label">Visual Price</div>
<div class="value" id="price">--</div>
</div>

<div class="card">
<div class="label">Confidence</div>
<div class="value" id="confidence">0%</div>
</div>

<div class="card">
<div class="label">Feed</div>
<div class="value" id="feed">
<span class="dot"></span>DISCONNECTED
</div>
</div>

<div class="card">
<div class="label">Current Signal</div>
<div class="signal wait" id="signal">WAIT</div>
</div>

<div class="card">
<div class="label">Entry</div>
<div class="value" id="entry">--</div>
</div>

<div class="card">
<div class="label">Entry Window</div>
<div class="value" id="window">--</div>
</div>

<div class="card">
<div class="label">Candles Received</div>
<div class="value" id="candles">0</div>
</div>

</div>

<div class="chart">
    <div>
        SCREEN FEED CHART ANALYSIS<br>
        <span class="small">
        Waiting for Android chart frames...
        </span>
    </div>
</div>

<div class="status" id="message">
Waiting for Android screen feed...
</div>

<div class="card" style="margin-top:12px">

<h3>Indicator Engine</h3>

<table>

<tr>
<td>EMA 9</td>
<td id="ema9">0</td>
</tr>

<tr>
<td>EMA 20</td>
<td id="ema20">0</td>
</tr>

<tr>
<td>EMA 50</td>
<td id="ema50">0</td>
</tr>

<tr>
<td>RSI</td>
<td id="rsi">50</td>
</tr>

<tr>
<td>MACD</td>
<td id="macd">0</td>
</tr>

<tr>
<td>CCI</td>
<td id="cci">0</td>
</tr>

<tr>
<td>Parabolic SAR</td>
<td id="sar">0</td>
</tr>

<tr>
<td>Alligator Jaw</td>
<td id="jaw">0</td>
</tr>

<tr>
<td>Alligator Teeth</td>
<td id="teeth">0</td>
</tr>

<tr>
<td>Alligator Lips</td>
<td id="lips">0</td>
</tr>

</table>

</div>

</div>

<script>

function setText(id, value) {
    const el = document.getElementById(id);

    if (el) {
        el.textContent = value;
    }
}

function update() {

    fetch("/api/state")
    .then(r => r.json())
    .then(d => {

        setText("asset", d.asset || "EURUSD_otc");

        setText(
            "price",
            d.price === null ? "--" : d.price
        );

        setText(
            "confidence",
            (d.confidence || 0) + "%"
        );

        const feed = document.getElementById("feed");

        if (d.feed === "LIVE") {
            feed.innerHTML =
                '<span class="dot live"></span>LIVE';
        } else {
            feed.innerHTML =
                '<span class="dot dead"></span>DISCONNECTED';
        }

        const signal = document.getElementById("signal");

        signal.textContent = d.signal || "WAIT";

        signal.className =
            "signal " +
            (d.signal === "WAIT" ? "wait" : "live");

        setText(
            "entry",
            d.entry === null ? "--" : d.entry
        );

        if (
            d.signal === "CALL" ||
            d.signal === "PUT"
        ) {
            setText(
                "window",
                "15 seconds"
            );
        } else {
            setText("window", "--");
        }

        setText("candles", d.candle_count || 0);

        setText("ema9", d.ema9 || 0);
        setText("ema20", d.ema20 || 0);
        setText("ema50", d.ema50 || 0);

        setText("rsi", d.rsi || 50);
        setText("macd", d.macd || 0);
        setText("cci", d.cci || 0);
        setText("sar", d.sar || 0);

        setText("jaw", d.jaw || 0);
        setText("teeth", d.teeth || 0);
        setText("lips", d.lips || 0);

        setText(
            "message",
            d.message || ""
        );

    })
    .catch(() => {
        setText(
            "message",
            "Dashboard connected — feed unavailable"
        );
    });
}

setInterval(update, 1000);
update();

</script>

</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(HTML)


# ============================================================
# FEED WATCHDOG
# ============================================================

def watchdog():
    while True:
        time.sleep(2)

        with lock:
            if state["last_frame"] > 0:
                if time.time() - state["last_frame"] > 8:
                    state["feed"] = "DISCONNECTED"


threading.Thread(
    target=watchdog,
    daemon=True
).start()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
One change to requirements.txt
Because this version reads the Android screenshots, add Pillow:
Flask==3.1.2
gunicorn==23.0.0
yfinance==0.2.65
pandas==2.3.2
numpy==2.3.2
Pillow==11.3.0
Render start command
Keep:
gunicorn main:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
After deployment, the dashboard can remain open at your Render URL. The next piece is the Android screen sender: it needs to POST each Pocket Option screenshot to:
/api/screen
No SSID is involved.
