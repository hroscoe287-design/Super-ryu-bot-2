from flask import Flask, request, jsonify, render_template_string
import time
import os

app = Flask(__name__)

STATE = {
    "asset": "EURUSD_otc",
    "price": None,
    "signal": "WAIT",
    "confidence": 0,
    "entry": None,
    "entry_window": 0,
    "candles": 0,
    "feed": "DISCONNECTED",
    "last_update": 0,
}


HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RYU V2 Signal Intelligence</title>
    <style>
        body {
            margin: 0;
            background: #07120b;
            color: white;
            font-family: Arial, sans-serif;
        }

        .top {
            padding: 18px;
            background: #101b14;
            border-bottom: 1px solid #23452d;
        }

        .title {
            font-size: 25px;
            font-weight: bold;
            color: #70ff8a;
        }

        .sub {
            color: #9fb3a3;
            margin-top: 4px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            padding: 15px;
        }

        .card {
            background: #102016;
            border: 1px solid #285335;
            border-radius: 12px;
            padding: 16px;
        }

        .label {
            color: #9caf9f;
            font-size: 13px;
        }

        .value {
            font-size: 23px;
            font-weight: bold;
            margin-top: 7px;
        }

        .signal {
            font-size: 38px;
            font-weight: bold;
            text-align: center;
            padding: 25px;
            margin: 15px;
            border-radius: 15px;
            background: #14291a;
            border: 1px solid #397348;
        }

        .feed {
            text-align: center;
            padding: 10px;
            color: #ffcc66;
        }

        .section {
            padding: 15px;
        }

        button {
            width: 100%;
            padding: 14px;
            border: 0;
            border-radius: 10px;
            background: #238636;
            color: white;
            font-size: 16px;
            font-weight: bold;
        }

        pre {
            white-space: pre-wrap;
            word-break: break-word;
        }
    </style>
</head>

<body>

<div class="top">
    <div class="title">🔥 RYU V2</div>
    <div class="sub">Signal Intelligence Dashboard</div>
</div>

<div class="feed" id="feed">Feed: DISCONNECTED</div>

<div class="signal" id="signal">WAIT</div>

<div class="grid">

    <div class="card">
        <div class="label">Asset</div>
        <div class="value" id="asset">EURUSD_otc</div>
    </div>

    <div class="card">
        <div class="label">Price</div>
        <div class="value" id="price">--</div>
    </div>

    <div class="card">
        <div class="label">Confidence</div>
        <div class="value" id="confidence">0%</div>
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
        <div class="label">Candles</div>
        <div class="value" id="candles">0</div>
    </div>

</div>

<div class="section">
    <button onclick="refresh()">REFRESH SIGNAL</button>
</div>

<div class="section">
    <div class="card">
        <b>Live State</b>
        <pre id="raw">Loading...</pre>
    </div>
</div>

<script>
async function refresh() {
    try {
        const response = await fetch("/api/state");
        const data = await response.json();

        document.getElementById("asset").textContent = data.asset || "--";
        document.getElementById("price").textContent =
            data.price === null ? "--" : data.price;

        document.getElementById("confidence").textContent =
            (data.confidence || 0) + "%";

        document.getElementById("entry").textContent =
            data.entry === null ? "--" : data.entry;

        document.getElementById("window").textContent =
            data.entry_window > 0 ? data.entry_window + " sec" : "--";

        document.getElementById("candles").textContent =
            data.candles || 0;

        document.getElementById("feed").textContent =
            "Feed: " + (data.feed || "DISCONNECTED");

        document.getElementById("signal").textContent =
            data.signal || "WAIT";

        document.getElementById("raw").textContent =
            JSON.stringify(data, null, 2);

    } catch (error) {
        document.getElementById("feed").textContent =
            "Feed: SERVER ERROR";
    }
}

refresh();
setInterval(refresh, 2000);
</script>

</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "RYU V2"
    })


@app.route("/api/state")
def api_state():
    state = dict(STATE)

    if state["last_update"]:
        age = time.time() - state["last_update"]

        if age > 15:
            state["feed"] = "STALE"

    return jsonify(state)


@app.route("/api/feed", methods=["POST"])
def api_feed():
    token = os.getenv("RYU_FEED_TOKEN", "")

    supplied = request.headers.get("X-RYU-TOKEN", "")

    if token and supplied != token:
        return jsonify({
            "ok": False,
            "error": "Invalid feed token"
        }), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "error": "JSON object required"
        }), 400

    for key in [
        "asset",
        "price",
        "signal",
        "confidence",
        "entry",
        "entry_window",
        "candles"
    ]:
        if key in data:
            STATE[key] = data[key]

    STATE["feed"] = "LIVE"
    STATE["last_update"] = time.time()

    return jsonify({
        "ok": True,
        "state": STATE
    })


@app.route("/api/ping")
def ping():
    return jsonify({
        "ok": True,
        "message": "RYU V2 server is running"
    })


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not Found",
        "message": "RYU V2 route does not exist",
        "available_routes": [
            "/",
            "/health",
            "/api/state",
            "/api/ping",
            "/api/feed"
        ]
    }), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
