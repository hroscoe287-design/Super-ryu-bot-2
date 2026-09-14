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
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RYU V2</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            background: #06110b;
            color: #ffffff;
            font-family: Arial, sans-serif;
        }

        .top {
            padding: 22px 18px 10px;
            text-align: center;
        }

        .title {
            font-size: 32px;
            font-weight: 900;
            letter-spacing: 3px;
            color: #39ff88;
            text-shadow: 0 0 15px #19ff70;
        }

        .subtitle {
            margin-top: 5px;
            color: #9bb8a5;
            font-size: 14px;
            letter-spacing: 1px;
        }

        .feed {
            margin: 15px auto;
            width: fit-content;
            padding: 8px 16px;
            border: 1px solid #263c2e;
            border-radius: 20px;
            color: #ff5555;
            background: #0b1710;
            font-weight: bold;
        }

        .grid {
            width: min(1000px, 94%);
            margin: 20px auto;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 14px;
        }

        .card {
            background: #0b1911;
            border: 1px solid #193a25;
            border-radius: 14px;
            padding: 18px;
            min-height: 105px;
            box-shadow: 0 0 20px rgba(0, 255, 100, 0.05);
        }

        .label {
            color: #86a994;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .value {
            margin-top: 10px;
            font-size: 25px;
            font-weight: 800;
        }

        .signal {
            grid-column: span 3;
            text-align: center;
            min-height: 150px;
        }

        .signal .value {
            font-size: 48px;
            color: #ffd84d;
        }

        .button {
            display: block;
            width: min(400px, 90%);
            margin: 25px auto;
            padding: 15px;
            border: 0;
            border-radius: 10px;
            background: #19d968;
            color: #001b0a;
            font-size: 16px;
            font-weight: 900;
            cursor: pointer;
        }

        .status {
            width: min(1000px, 94%);
            margin: 20px auto;
            padding: 16px;
            background: #08150d;
            border: 1px solid #193a25;
            border-radius: 12px;
        }

        .live {
            color: #39ff88;
        }

        .dead {
            color: #ff5555;
        }

        @media (max-width: 700px) {
            .grid {
                grid-template-columns: 1fr 1fr;
            }

            .signal {
                grid-column: span 2;
            }

            .title {
                font-size: 25px;
            }
        }
    </style>
</head>

<body>

<div class="top">
    <div class="title">RYU V2</div>
    <div class="subtitle">SIGNAL INTELLIGENCE DASHBOARD</div>
    <div id="feed" class="feed">Feed: DISCONNECTED</div>
</div>

<div class="grid">

    <div class="card">
        <div class="label">Asset</div>
        <div id="asset" class="value">EURUSD_otc</div>
    </div>

    <div class="card">
        <div class="label">Price</div>
        <div id="price" class="value">--</div>
    </div>

    <div class="card">
        <div class="label">Confidence</div>
        <div id="confidence" class="value">0%</div>
    </div>

    <div class="card signal">
        <div class="label">Signal</div>
        <div id="signal" class="value">WAIT</div>
    </div>

    <div class="card">
        <div class="label">Entry</div>
        <div id="entry" class="value">--</div>
    </div>

    <div class="card">
        <div class="label">Entry Window</div>
        <div id="entry_window" class="value">--</div>
    </div>

    <div class="card">
        <div class="label">Candles</div>
        <div id="candles" class="value">0</div>
    </div>

</div>

<button class="button" onclick="refreshSignal()">REFRESH SIGNAL</button>

<div class="status">
    <div class="label">Live State</div>
    <div id="liveState" class="value">Waiting for feed...</div>
</div>

<script>
async function refreshSignal() {
    try {
        const response = await fetch("/api/state", {
            cache: "no-store"
        });

        const data = await response.json();

        document.getElementById("asset").textContent =
            data.asset || "EURUSD_otc";

        document.getElementById("price").textContent =
            data.price !== null && data.price !== undefined
                ? data.price
                : "--";

        document.getElementById("confidence").textContent =
            (data.confidence || 0) + "%";

        document.getElementById("signal").textContent =
            data.signal || "WAIT";

        document.getElementById("entry").textContent =
            data.entry !== null && data.entry !== undefined
                ? data.entry
                : "--";

        document.getElementById("entry_window").textContent =
            data.entry_window
                ? data.entry_window + "s"
                : "--";

        document.getElementById("candles").textContent =
            data.candles || 0;

        const feed = document.getElementById("feed");
        const liveState = document.getElementById("liveState");

        if (data.feed === "LIVE") {
            feed.textContent = "Feed: LIVE";
            feed.className = "feed live";
            liveState.textContent = "LIVE";
            liveState.className = "value live";
        } else {
            feed.textContent = "Feed: DISCONNECTED";
            feed.className = "feed dead";
            liveState.textContent = "Waiting for feed...";
            liveState.className = "value dead";
        }

    } catch (error) {
        document.getElementById("feed").textContent =
            "Feed: DISCONNECTED";
    }
}

refreshSignal();

setInterval(refreshSignal, 1000);
</script>

</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/state")
def api_state():
    # Mark feed disconnected if no update for 15 seconds.
    if STATE["last_update"]:
        age = time.time() - STATE["last_update"]

        if age > 15:
            STATE["feed"] = "DISCONNECTED"

    return jsonify(STATE)


@app.route("/api/feed", methods=["POST"])
def api_feed():
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "ok": False,
                "error": "No JSON data received"
            }), 400

        # Accept common field names.
        asset = (
            data.get("asset")
            or data.get("symbol")
            or data.get("pair")
        )

        price = (
            data.get("price")
            if data.get("price") is not None
            else data.get("close")
        )

        candles = data.get("candles")

        if asset:
            STATE["asset"] = str(asset)

        if price is not None:
            STATE["price"] = price

        if candles is not None:
            try:
                STATE["candles"] = int(candles)
            except (ValueError, TypeError):
                pass

        # Optional signal data from bridge/engine.
        if data.get("signal") is not None:
            STATE["signal"] = str(data["signal"]).upper()

        if data.get("confidence") is not None:
            try:
                STATE["confidence"] = int(float(data["confidence"]))
            except (ValueError, TypeError):
                pass

        if data.get("entry") is not None:
            STATE["entry"] = data["entry"]

        if data.get("entry_window") is not None:
            try:
                STATE["entry_window"] = int(
                    float(data["entry_window"])
                )
            except (ValueError, TypeError):
                pass

        STATE["feed"] = "LIVE"
        STATE["last_update"] = time.time()

        return jsonify({
            "ok": True,
            "state": STATE
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "RYU V2",
        "feed": STATE["feed"]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
