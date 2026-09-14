import os
import json
import time
import math
import random
import threading
from datetime import datetime, timezone

import websocket
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template_string


app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

PO_SERVER = os.getenv(
    "PO_SERVER",
    "wss://try-demo-eu.po.market/socket.io/?EIO=4&transport=websocket"
)

DEFAULT_ASSET = os.getenv("RYU_DEFAULT_ASSET", "EURUSD_otc")
DEFAULT_PERIOD = int(os.getenv("RYU_PERIOD_SECONDS", "60"))

FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "")
DEMO_BALANCE = 50000

STALE_SECONDS = 8
CANDLE_SECONDS = DEFAULT_PERIOD

ASSETS = [
    ("EURUSD_otc", "EUR/USD OTC"),
    ("GBPUSD_otc", "GBP/USD OTC"),
    ("USDJPY_otc", "USD/JPY OTC"),
    ("AUDUSD_otc", "AUD/USD OTC"),
    ("USDCAD_otc", "USD/CAD OTC"),
    ("USDCHF_otc", "USD/CHF OTC"),
    ("NZDUSD_otc", "NZD/USD OTC"),
    ("EURJPY_otc", "EUR/JPY OTC"),
    ("GBPJPY_otc", "GBP/JPY OTC"),

    ("BTCUSD_otc", "BTC/USD OTC"),
    ("ETHUSD_otc", "ETH/USD OTC"),
    ("SOL-USD_otc", "SOL/USD OTC"),
    ("XRP_otc", "XRP/USD OTC"),
    ("DOGE_otc", "DOGE/USD OTC"),

    ("MSFT_otc", "Microsoft OTC"),
    ("TSLA_otc", "Tesla OTC"),
    ("AMZN_otc", "Amazon OTC"),
    ("NFLX_otc", "Netflix OTC"),
    ("GME_otc", "GameStop OTC"),
    ("VISA_otc", "Visa OTC"),

    ("SP500_otc", "S&P 500 OTC"),
    ("NASUSD_otc", "Nasdaq OTC"),
    ("DJI30_otc", "Dow Jones OTC"),
    ("JPN225_otc", "Japan 225 OTC"),
    ("F40EUR_otc", "France 40 OTC"),
    ("E50EUR_otc", "Euro 50 OTC"),

    ("UKBrent_otc", "UK Brent OTC"),
    ("USCrude_otc", "US Crude OTC"),
    ("XAUUSD_otc", "Gold OTC"),
    ("XAGUSD_otc", "Silver OTC"),
    ("XNGUSD_otc", "Natural Gas OTC"),
]


# ============================================================
# GLOBAL STATE
# ============================================================

state_lock = threading.Lock()

state = {
    "asset": DEFAULT_ASSET,
    "period": DEFAULT_PERIOD,

    "connected": False,
    "authenticated": False,
    "subscribed": False,

    "price": None,
    "last_tick": None,
    "last_tick_text": "--",

    "ticks": 0,
    "candles": [],

    "signal": "WAIT",
    "confidence": 0,
    "reason": "Waiting for market data",

    "ema9": None,
    "ema20": None,
    "ema50": None,
    "rsi": None,
    "macd": None,
    "macd_signal": None,
    "cci": None,
    "bb_upper": None,
    "bb_middle": None,
    "bb_lower": None,

    "entry_price": None,
    "entry_time": None,
    "entry_deadline": None,

    "feed_message": "CONNECTING",
    "server_time": None,
}


# ============================================================
# DEMO TOKEN
# ============================================================

def make_demo_token():
    if FEED_TOKEN and len(FEED_TOKEN) >= 10:
        return FEED_TOKEN

    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(10))


DEMO_TOKEN = make_demo_token()


# ============================================================
# HELPERS
# ============================================================

def now_unix():
    return time.time()


def format_price(value):
    if value is None:
        return "--"

    try:
        value = float(value)

        if value >= 1000:
            return f"{value:,.2f}"

        if value >= 10:
            return f"{value:.3f}"

        return f"{value:.5f}"

    except Exception:
        return "--"


def period_label(seconds):
    mapping = {
        1: "1s",
        5: "5s",
        10: "10s",
        15: "15s",
        30: "30s",
        60: "1m",
        120: "2m",
        180: "3m",
        300: "5m",
        600: "10m",
        900: "15m",
        1800: "30m",
        3600: "1h",
        14400: "4h",
        86400: "1D",
    }

    return mapping.get(seconds, f"{seconds}s")


def current_candle_bucket(timestamp, seconds):
    return int(timestamp // seconds) * seconds


# ============================================================
# CANDLE BUILDER
# ============================================================

def add_tick(asset, timestamp, price):
    global state

    if asset != state["asset"]:
        return

    try:
        timestamp = float(timestamp)
        price = float(price)
    except Exception:
        return

    with state_lock:
        state["price"] = price
        state["last_tick"] = timestamp
        state["last_tick_text"] = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc
        ).strftime("%H:%M:%S UTC")

        state["ticks"] += 1
        state["server_time"] = timestamp

        bucket = current_candle_bucket(
            timestamp,
            state["period"]
        )

        candles = state["candles"]

        if not candles or candles[-1]["time"] != bucket:
            candles.append({
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            })

        else:
            candle = candles[-1]

            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price

        # Keep enough history without allowing unlimited memory growth.
        if len(candles) > 500:
            del candles[:-500]

        calculate_indicators_locked()


# ============================================================
# INDICATORS
# ============================================================

def calculate_indicators_locked():
    candles = state["candles"]

    if len(candles) < 20:
        state["signal"] = "WAIT"
        state["confidence"] = 0
        state["reason"] = (
            f"Building candles "
            f"({len(candles)}/50)"
        )
        return

    df = pd.DataFrame(candles)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMA
    df["ema9"] = close.ewm(
        span=9,
        adjust=False
    ).mean()

    df["ema20"] = close.ewm(
        span=20,
        adjust=False
    ).mean()

    df["ema50"] = close.ewm(
        span=50,
        adjust=False
    ).mean()

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["rsi"] = 100 - (
        100 / (1 + rs)
    )

    # MACD
    ema12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    df["macd"] = ema12 - ema26

    df["macd_signal"] = df["macd"].ewm(
        span=9,
        adjust=False
    ).mean()

    # CCI
    typical = (high + low + close) / 3

    sma20 = typical.rolling(20).mean()

    mean_dev = typical.rolling(20).apply(
        lambda x: np.mean(
            np.abs(x - np.mean(x))
        ),
        raw=True
    )

    df["cci"] = (
        (typical - sma20) /
        (0.015 * mean_dev.replace(0, np.nan))
    )

    # Bollinger Bands
    bb_middle = close.rolling(20).mean()
    bb_std = close.rolling(20).std()

    df["bb_middle"] = bb_middle
    df["bb_upper"] = bb_middle + (2 * bb_std)
    df["bb_lower"] = bb_middle - (2 * bb_std)

    latest = df.iloc[-1]

    values = [
        latest["ema9"],
        latest["ema20"],
        latest["ema50"],
        latest["rsi"],
        latest["macd"],
        latest["macd_signal"],
        latest["cci"],
        latest["bb_upper"],
        latest["bb_middle"],
        latest["bb_lower"],
    ]

    if any(pd.isna(v) for v in values):
        state["signal"] = "WAIT"
        state["confidence"] = 0
        state["reason"] = "Indicators warming up"
        return

    state["ema9"] = float(latest["ema9"])
    state["ema20"] = float(latest["ema20"])
    state["ema50"] = float(latest["ema50"])

    state["rsi"] = float(latest["rsi"])

    state["macd"] = float(latest["macd"])
    state["macd_signal"] = float(
        latest["macd_signal"]
    )

    state["cci"] = float(latest["cci"])

    state["bb_upper"] = float(latest["bb_upper"])
    state["bb_middle"] = float(latest["bb_middle"])
    state["bb_lower"] = float(latest["bb_lower"])

    # ========================================================
    # SIGNAL ENGINE
    # ========================================================

    call_score = 0
    put_score = 0
    reasons_call = []
    reasons_put = []

    current = float(latest["close"])

    # EMA trend
    if latest["ema9"] > latest["ema20"]:
        call_score += 15
        reasons_call.append("EMA9 > EMA20")

    elif latest["ema9"] < latest["ema20"]:
        put_score += 15
        reasons_put.append("EMA9 < EMA20")

    if latest["ema20"] > latest["ema50"]:
        call_score += 15
        reasons_call.append("EMA20 > EMA50")

    elif latest["ema20"] < latest["ema50"]:
        put_score += 15
        reasons_put.append("EMA20 < EMA50")

    # MACD
    if latest["macd"] > latest["macd_signal"]:
        call_score += 15
        reasons_call.append("MACD bullish")

    elif latest["macd"] < latest["macd_signal"]:
        put_score += 15
        reasons
