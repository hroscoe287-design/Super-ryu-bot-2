import os
import time
import json
import logging
import threading
from flask import Flask, request, jsonify

import requests

# ============================================================
# RYU V2 FEED BRIDGE
# ============================================================

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

RYU_URL = os.getenv(
    "RYU_URL",
    "https://super-ryu-bot.onrender.com"
).rstrip("/")

RYU_FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "")

DEFAULT_ASSET = os.getenv(
    "RYU_DEFAULT_ASSET",
    "EURUSD_otc"
)

REQUEST_TIMEOUT = int(
    os.getenv("RYU_REQUEST_TIMEOUT", "10")
)

# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

STATE = {
    "connected": False,
    "last_tick": 0,
    "ticks_received": 0,
    "ticks_forwarded": 0,
    "last_asset": DEFAULT_ASSET,
    "last_price": None,
    "last_error": "",
}

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def normalize_asset(asset):
    if not asset:
        return DEFAULT_ASSET

    return str(asset).strip()


def normalize_price(price):
    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def normalize_timestamp(value):
    if value is None:
        return time.time()

    try:
        return float(value)
    except (TypeError, ValueError):
        return time.time()


# ------------------------------------------------------------
# SEND TICK TO RYU
# ------------------------------------------------------------

def send_to_ryu(asset, timestamp, price):
    payload = {
        "asset": asset,
        "timestamp": timestamp,
        "price": price
    }

    headers = {
        "Content-Type": "application/json"
    }

    if RYU_FEED_TOKEN:
        headers["X-RYU-FEED-TOKEN"] = RYU_FEED_TOKEN

    try:
        response = requests.post(
            f"{RYU_URL}/api/feed",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        if 200 <= response.status_code < 300:
            STATE["connected"] = True
            STATE["ticks_forwarded"] += 1
            STATE["last_error"] = ""

            return True

        STATE["connected"] = False
        STATE["last_error"] = (
            f"Ryu returned HTTP {response.status_code}"
        )

        logging.warning(
            "%s",
            STATE["last_error"]
        )

        return False

    except requests.RequestException as exc:
        STATE["connected"] = False
        STATE["last_error"] = str(exc)

        logging.warning(
            "Unable to reach Ryu: %s",
            exc
        )

        return False


# ------------------------------------------------------------
# TICK PROCESSOR
# ------------------------------------------------------------

def process_tick(asset, timestamp, price):

    asset = normalize_asset(asset)
    timestamp = normalize_timestamp(timestamp)
    price = normalize_price(price)

    if price is None:
        return False, "Invalid price"

    STATE["last_tick"] = time.time()
    STATE["ticks_received"] += 1
    STATE["last_asset"] = asset
    STATE["last_price"] = price

    success = send_to_ryu(
        asset,
        timestamp,
        price
    )

    if success:
        logging.info(
            "FORWARDED | %s | %.8f",
            asset,
            price
        )

        return True, "Forwarded"

    return False, STATE["last_error"]


# ------------------------------------------------------------
# HOME
# ------------------------------------------------------------

@app.route("/")
def index():

    return jsonify({
        "service": "Ryu V2 Feed Bridge",
        "status": "online",
        "ryu_url": RYU_URL,
        "default_asset": DEFAULT_ASSET,
        "ticks_received": STATE["ticks_received"],
        "ticks_forwarded": STATE["ticks_forwarded"],
        "last_asset": STATE["last_asset"],
        "last_price": STATE["last_price"],
        "connected_to_ryu": STATE["connected"],
        "last_error": STATE["last_error"]
    })


# ------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bridge": "online",
        "ryu_connected": STATE["connected"],
        "ticks_received": STATE["ticks_received"],
        "ticks_forwarded": STATE["ticks_forwarded"],
        "last_tick": STATE["last_tick"],
        "last_error": STATE["last_error"]
    })


# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

@app.route("/api/state")
def api_state():

    return jsonify({
        "bridge": "online",
        "connected": STATE["connected"],
        "ticks_received": STATE["ticks_received"],
        "ticks_forwarded": STATE["ticks_forwarded"],
        "last_tick": STATE["last_tick"],
        "last_asset": STATE["last_asset"],
        "last_price": STATE["last_price"],
        "last_error": STATE["last_error"],
        "ryu_url": RYU_URL
    })


# ------------------------------------------------------------
# FEED ENDPOINT
# ------------------------------------------------------------

@app.route("/feed", methods=["POST"])
def feed():

    try:
        data = request.get_json(
            force=True,
            silent=True
        )

        if not data:
            return jsonify({
                "ok": False,
                "error": "No JSON data received"
            }), 400

        # ----------------------------------------------------
        # NORMAL JSON FORMAT
        # ----------------------------------------------------

        if isinstance(data, dict):

            asset = data.get(
                "asset",
                data.get(
                    "symbol",
                    DEFAULT_ASSET
                )
            )

            timestamp = data.get(
                "timestamp",
                data.get(
                    "time",
                    time.time()
                )
            )

            price = data.get(
                "price",
                data.get(
                    "close"
                )
            )

            success, message = process_tick(
                asset,
                timestamp,
                price
            )

            return jsonify({
                "ok": success,
                "message": message,
                "asset": normalize_asset(asset),
                "price": normalize_price(price)
            }), (200 if success else 502)

        # ----------------------------------------------------
        # ARRAY FORMAT
        #
        # Example:
        # ["EURUSD_otc", 1789394801.128, 1.15181]
        # ----------------------------------------------------

        if isinstance(data, list):

            if len(data) >= 3:

                asset = data[0]
                timestamp = data[1]
                price = data[2]

                success, message = process_tick(
                    asset,
                    timestamp,
                    price
                )

                return jsonify({
                    "ok": success,
                    "message": message,
                    "asset": normalize_asset(asset),
                    "price": normalize_price(price)
                }), (200 if success else 502)

            return jsonify({
                "ok": False,
                "error": "Array feed requires asset, timestamp, price"
            }), 400

        return jsonify({
            "ok": False,
            "error": "Unsupported JSON format"
        }), 400

    except Exception as exc:

        STATE["last_error"] = str(exc)

        logging.exception(
            "Feed processing error"
        )

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ------------------------------------------------------------
# API FEED ALIAS
# ------------------------------------------------------------

@app.route("/api/feed", methods=["POST"])
def api_feed():

    return feed()


# ------------------------------------------------------------
# TEST FEED
# ------------------------------------------------------------

@app.route("/test-feed", methods=["GET"])
def test_feed():

    price = 1.15181
    timestamp = time.time()

    success, message = process_tick(
        DEFAULT_ASSET,
        timestamp,
        price
    )

    return jsonify({
        "ok": success,
        "message": message,
        "asset": DEFAULT_ASSET,
        "price": price,
        "timestamp": timestamp
    }), (200 if success else 502)


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
