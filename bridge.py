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


def send_to_ryu(asset, timestamp, price):
    """
    Forward one normalized tick to Ryu /api/feed.
    """

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

        logging.warning(STATE["last_error"])
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
# HEALTH
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


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "bridge": "online",
        "ryu_connected": STATE["connected"],
        "ticks_received": STATE["ticks_received"],
        "ticks_forwarded": STATE["ticks_forwarded"]
    })


# ------------------------------------------------------------
# FEED ENDPOINT
# ------------------------------------------------------------

@app.route("/feed", methods=["POST"])
def feed():
    """
    Accepts JSON such as:

    {
        "asset": "EURUSD_otc",
        "timestamp": 1789394801.128,
        "price": 1.15181
    }

    Also accepts:

    {
       
