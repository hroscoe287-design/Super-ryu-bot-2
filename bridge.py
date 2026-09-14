import os
import json
import time
import logging
import threading
import requests
import websocket

# ============================================================
# RYU V2 — POCKET OPTION WEBSOCKET FEED BRIDGE
# ============================================================
#
# Pocket Option WebSocket
#        ↓
#      ticks
#        ↓
#   this bridge
#        ↓
# POST /api/feed
#        ↓
#      RYU V2
#
# This program ONLY forwards market data.
# It does NOT place trades.
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ------------------------------------------------------------
# RYU
# ------------------------------------------------------------

RYU_URL = os.getenv(
    "RYU_URL",
    "https://super-ryu-bot.onrender.com"
).rstrip("/")

RYU_FEED_TOKEN = os.getenv(
    "RYU_FEED_TOKEN",
    ""
).strip()

FEED_ENDPOINT = f"{RYU_URL}/api/feed"

# ------------------------------------------------------------
# POCKET OPTION
# ------------------------------------------------------------

PO_WS_URL = os.getenv(
    "PO_WS_URL",
    "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket"
).strip()

PO_SSID = os.getenv("PO_SSID", "").strip()

PO_ASSET = os.getenv(
    "PO_ASSET",
    "EURUSD_otc"
).strip()

PO_PERIOD = int(os.getenv("PO_PERIOD", "60"))

# Demo by default.
PO_IS_DEMO = int(os.getenv("PO_IS_DEMO", "1"))

# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

SESSION = requests.Session()

SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "Ryu-V2-Feed-Bridge/2.0"
})

# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

last_price = {}
last_timestamp = {}

running = True


# ============================================================
# RYU FEED
# ============================================================

def send_tick(asset, timestamp, price):

    payload = {
        "asset": str(asset),
        "timestamp": float(timestamp),
        "price": float(price)
    }

    headers = {}

    if RYU_FEED_TOKEN:
        headers["Authorization"] = (
            f"Bearer {RYU_FEED_TOKEN}"
        )

        headers["X-RYU-FEED-TOKEN"] = RYU_FEED_TOKEN

    try:

        response = SESSION.post(
            FEED_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=10
        )

        if response.ok:

            logging.info(
                "RYU FEED OK | %s | %.8f | HTTP %s",
                asset,
                price,
                response.status_code
            )

            return True

        logging.error(
            "RYU FEED REJECTED | HTTP %s | %s",
            response.status_code,
            response.text[:300]
        )

    except requests.RequestException as exc:

        logging.error(
            "RYU FEED ERROR | %s",
            exc
        )

    return False


# ============================================================
# NORMALIZE TICK
# ============================================================

def forward_tick(asset, timestamp, price):

    try:

        asset = str(asset)
        timestamp = float(timestamp)
        price = float(price)

    except (TypeError, ValueError):

        return False

    if not asset or price <= 0:
        return False

    # Ignore exact duplicates.
    if (
        last_timestamp.get(asset) == timestamp
        and last_price.get(asset) == price
    ):
        return False

    last_timestamp[asset] = timestamp
    last_price[asset] = price

    return send_tick(
        asset,
        timestamp,
        price
    )


# ============================================================
# JSON TICK PARSER
# ============================================================

def parse_tick_object(obj):

    """
    Handles:

    [
        ["EURUSD_otc", timestamp, price]
    ]

    and some common updateStream structures.
    """

    # --------------------------------------------------------
    # Simple captured format
    # --------------------------------------------------------

    if isinstance(obj, list):

        if (
            len(obj) >= 1
            and isinstance(obj[0], list)
        ):

            row = obj[0]

            if len(row) >= 3:

                asset = row[0]
                timestamp = row[1]
                price = row[2]

                try:

                    return (
                        str(asset),
                        float(timestamp),
                        float(price)
                    )

                except (TypeError, ValueError):

                    pass

        # Some updateStream messages may contain
        # multiple rows.

        for row in obj:

            if not isinstance(row, list):
                continue

            if len(row) < 3:
                continue

            try:

                asset = str(row[0])
                timestamp = float(row[1])
                price = float(row[2])

                if asset and price > 0:

                    return (
                        asset,
                        timestamp,
                        price
                    )

            except (TypeError, ValueError):

                continue

    # --------------------------------------------------------
    # Dictionary format
    # --------------------------------------------------------

    if isinstance(obj, dict):

        asset = (
            obj.get("asset")
            or obj.get("symbol")
            or obj.get("instrument")
        )

        timestamp = (
            obj.get("timestamp")
            or obj.get("time")
            or obj.get("ts")
        )

        price = (
            obj.get("price")
            or obj.get("close")
            or obj.get("value")
        )

        if asset is not None:

            try:

                return (
                    str(asset),
                    float(timestamp),
                    float(price)
                )

            except (TypeError, ValueError):

                pass

    return None


# ============================================================
# POCKET OPTION MESSAGE PARSER
# ============================================================

def parse_pocket_message(message):

    if isinstance(message, bytes):

        message = message.decode(
            "utf-8",
            errors="ignore"
        )

    message = str(message).strip()

    if not message:
        return None

    # --------------------------------------------------------
    # Socket.IO heartbeat
    # --------------------------------------------------------

    if message in ("2", "3", "40"):

        return None

    # --------------------------------------------------------
    # Binary placeholder messages
    # Example:
    #
    # 451-["updateStream",{"_placeholder":true,"num":0}]
    #
    # The actual data may arrive as a binary frame.
    # --------------------------------------------------------

    if message.startswith("451-"):

        logging.debug(
            "Binary placeholder: %s",
            message[:200]
        )

        return None

    # --------------------------------------------------------
    # Socket.IO event
    #
    # 42["updateStream", ...]
    # --------------------------------------------------------

    if message.startswith("42"):

        payload = message[2:]

        try:

            data = json.loads(payload)

        except json.JSONDecodeError:

            return None

        if not isinstance(data, list):
            return None

        if len(data) < 2:
            return None

        event = data[0]
        body = data[1]

        if event == "updateStream":

            result = parse_tick_object(body)

            if result:
                return result

        return None

    # --------------------------------------------------------
    # Plain JSON
    # --------------------------------------------------------

    try:

        data = json.loads(message)

    except json.JSONDecodeError:

        return None

    return parse_tick_object(data)


# ============================================================
# AUTH MESSAGE
# ============================================================

def build_auth_message():

    """
    PO_SSID should normally contain the complete captured
    Socket.IO auth message, for example:

    42["auth",{"session":"...","isDemo":1,"uid":123456,...}]

    If the variable contains the complete message, send it
    unchanged.

    If it contains only JSON, wrap it automatically.
    """

    if not PO_SSID:

        return None

    ssid = PO_SSID.strip()

    # Complete Socket.IO auth message.
    if ssid.startswith("42"):

        return ssid

    # JSON auth object.
    if ssid.startswith("{"):

        try:

            auth_object = json.loads(ssid)

            return (
                "42"
                + json.dumps(
                    ["auth", auth_object],
                    separators=(",", ":")
                )
            )

        except json.JSONDecodeError:

            pass

    # Try extracting an auth payload that may have
    # been pasted with surrounding whitespace.

    if "42[\"auth\"" in ssid:

        position = ssid.find("42[\"auth\"")

        return ssid[position:]

    return None


# ============================================================
# SUBSCRIBE MESSAGE
# ============================================================

def build_subscribe_messages():

    """
    These are Socket.IO requests used by Pocket Option
    clients to request an asset stream.
    """

    messages = []

    messages.append(
        "42"
        + json.dumps(
            [
                "subscribeSymbol",
                {
                    "asset": PO_ASSET
                }
            ],
            separators=(",", ":")
        )
    )

    messages.append(
        "42"
        + json.dumps(
            [
                "changeSymbol",
                {
                    "asset": PO_ASSET,
                    "period": PO_PERIOD
                }
            ],
            separators=(",", ":")
        )
    )

    return messages


# ============================================================
# WEBSOCKET OPEN
# ============================================================

def on_open(ws):

    logging.info(
        "POCKET OPTION WEBSOCKET CONNECTED"
    )

    auth = build_auth_message()

    if not auth:

        logging.error(
            "PO_SSID is missing or invalid."
        )

        logging.error(
            "Set PO_SSID in Render Environment."
        )

        ws.close()

        return

    try:

        ws.send(auth)

        logging.info(
            "Pocket Option authentication sent."
        )

    except Exception as exc:

        logging.error(
            "AUTH SEND ERROR | %s",
            exc
        )

        return

    # Give the server a moment to authenticate.
    time.sleep(2)

    for message in build_subscribe_messages():

        try:

            ws.send(message)

            logging.info(
                "SUBSCRIBE SENT | %s",
                PO_ASSET
            )

        except Exception as exc:

            logging.error(
                "SUBSCRIBE ERROR | %s",
                exc
            )


# ============================================================
# WEBSOCKET MESSAGE
# ============================================================

def on_message(ws, message):

    if isinstance(message, bytes):

        logging.debug(
            "BINARY FRAME RECEIVED | %d bytes",
            len(message)
        )

    result = parse_pocket_message(message)

    if not result:
        return

    asset, timestamp, price = result

    logging.info(
        "POCKET OPTION TICK | %s | %.8f",
        asset,
        price
    )

    forward_tick(
        asset,
        timestamp,
        price
    )


# ============================================================
# WEBSOCKET ERROR
# ============================================================

def on_error(ws, error):

    logging.error(
        "POCKET OPTION WEBSOCKET ERROR | %s",
        error
    )


# ============================================================
# WEBSOCKET CLOSE
# ============================================================

def on_close(ws, close_status_code, close_msg):

    logging.warning(
        "POCKET OPTION DISCONNECTED | code=%s | msg=%s",
        close_status_code,
        close_msg
    )


# ============================================================
# RYU TEST
# ============================================================

def test_ryu():

    try:

        response = SESSION.get(
            f"{RYU_URL}/api/state",
            timeout=10
        )

        logging.info(
            "RYU TEST | HTTP %s",
            response.status_code
        )

        if response.ok:

            logging.info(
                "RYU SERVER REACHABLE."
            )

            return True

        logging.error(
            "RYU SERVER RETURNED HTTP %s",
            response.status_code
        )

    except requests.RequestException as exc:

        logging.error(
            "RYU TEST FAILED | %s",
            exc
        )

    return False


# ============================================================
# CONNECTION LOOP
# ============================================================

def websocket_loop():

    while running:

        logging.info(
            "Connecting to Pocket Option:"
        )

        logging.info(
            "%s",
            PO_WS_URL
        )

        try:

            ws = websocket.WebSocketApp(
                PO_WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as exc:

            logging.error(
                "WEBSOCKET LOOP ERROR | %s",
                exc
            )

        if running:

            logging.info(
                "Reconnecting in 5 seconds..."
            )

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    logging.info("")
    logging.info(
        "=========================================="
    )
    logging.info(
        "RYU V2 POCKET OPTION FEED BRIDGE"
    )
    logging.info(
        "=========================================="
    )

    logging.info(
        "Ryu server: %s",
        RYU_URL
    )

    logging.info(
        "Feed endpoint: %s",
        FEED_ENDPOINT
    )

    logging.info(
        "Pocket Option asset: %s",
        PO_ASSET
    )

    logging.info(
        "Pocket Option period: %s",
        PO_PERIOD
    )

    logging.info(
        "Demo mode: %s",
        PO_IS_DEMO
    )

    if RYU_FEED_TOKEN:

        logging.info(
            "RYU_FEED_TOKEN: CONFIGURED"
        )

    else:

        logging.warning(
            "RYU_FEED_TOKEN: NOT CONFIGURED"
        )

    if PO_SSID:

        logging.info(
            "PO_SSID: CONFIGURED"
        )

    else:

        logging.error(
            "PO_SSID: NOT CONFIGURED"
        )

        logging.error(
            "The bridge cannot authenticate without PO_SSID."
        )

    logging.info(
        "Testing Ryu..."
    )

    test_ryu()

    if not PO_SSID:

        logging.error(
            "Bridge stopped because PO_SSID is missing."
        )

        return

    websocket_loop()


if __name__ == "__main__":

    main()
