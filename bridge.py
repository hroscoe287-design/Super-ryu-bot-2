import os
import json
import time
import logging
import requests

# ============================================================
# RYU V2 POCKET OPTION FEED BRIDGE
# ============================================================
#
# Receives Pocket Option-style tick messages such as:
#
# [["EURUSD_otc",1789394801.128,1.15181]]
#
# and forwards them to:
#
# https://super-ryu-bot.onrender.com/api/feed
#
# This bridge ONLY forwards market data.
# It does NOT place trades.
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

RYU_URL = os.getenv(
    "RYU_URL",
    "https://super-ryu-bot.onrender.com"
).rstrip("/")

RYU_FEED_TOKEN = os.getenv("RYU_FEED_TOKEN", "").strip()

FEED_ENDPOINT = f"{RYU_URL}/api/feed"

SESSION = requests.Session()
SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "Ryu-V2-Feed-Bridge/1.0"
})

last_price = {}
last_sent = {}


def send_tick(asset, timestamp, price):
    """Send one normalized tick to Ryu."""

    payload = {
        "asset": str(asset),
        "timestamp": float(timestamp),
        "price": float(price)
    }

    headers = {}

    if RYU_FEED_TOKEN:
        headers["Authorization"] = f"Bearer {RYU_FEED_TOKEN}"
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
                "FORWARDED | %s | %.8f | HTTP %s",
                asset,
                price,
                response.status_code
            )
            return True

        logging.error(
            "RYU REJECTED | HTTP %s | %s",
            response.status_code,
            response.text[:300]
        )

    except requests.RequestException as exc:
        logging.error("RYU CONNECTION ERROR | %s", exc)

    return False


def parse_tick(message):
    """
    Parse Pocket Option-style data.

    Supported examples:

    [["EURUSD_otc",1789394801.128,1.15181]]

    or:

    b'[["EURUSD_otc",1789394801.128,1.15181]]'
    """

    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="ignore")

    message = str(message).strip()

    # Remove Python bytes representation if present.
    if message.startswith("b'") and message.endswith("'"):
        message = message[2:-1]

    elif message.startswith('b"') and message.endswith('"'):
        message = message[2:-1]

    # Decode escaped content if necessary.
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    if not data:
        return None

    # Expected:
    # [
    #   ["EURUSD_otc", timestamp, price]
    # ]
    first = data[0]

    if not isinstance(first, list):
        return None

    if len(first) < 3:
        return None

    asset = first[0]
    timestamp = first[1]
    price = first[2]

    try:
        timestamp = float(timestamp)
        price = float(price)
    except (TypeError, ValueError):
        return None

    if not asset or price <= 0:
        return None

    return {
        "asset": str(asset),
        "timestamp": timestamp,
        "price": price
    }


def process_message(message):
    tick = parse_tick(message)

    if not tick:
        logging.debug("Ignored non-price message: %s", message)
        return False

    asset = tick["asset"]
    timestamp = tick["timestamp"]
    price = tick["price"]

    last_price[asset] = price

    # Prevent accidental duplicate forwarding.
    duplicate_key = (asset, timestamp, price)

    if last_sent.get(asset) == duplicate_key:
        return False

    if send_tick(asset, timestamp, price):
        last_sent[asset] = duplicate_key
        return True

    return False


def test_ryu():
    """Check that the Ryu server is reachable."""

    try:
        response = SESSION.get(
            f"{RYU_URL}/api/state",
            timeout=10
        )

        logging.info(
            "RYU TEST | HTTP %s | %s",
            response.status_code,
            response.text[:500]
        )

        return response.ok

    except requests.RequestException as exc:
        logging.error("RYU TEST FAILED | %s", exc)
        return False


def demo_test():
    """
    Sends the exact type of tick you captured earlier.

    REMOVE/COMMENT THIS CALL when using the real live feed.
    """

    sample = '[[\"EURUSD_otc\",1789394801.128,1.15181]]'

    logging.info("Running feed test...")
    process_message(sample)


def main():
    logging.info("==========================================")
    logging.info("RYU V2 FEED BRIDGE")
    logging.info("==========================================")
    logging.info("Ryu server: %s", RYU_URL)
    logging.info("Feed endpoint: %s", FEED_ENDPOINT)

    if RYU_FEED_TOKEN:
        logging.info("Feed token: CONFIGURED")
    else:
        logging.info("Feed token: NOT CONFIGURED")

    logging.info("Testing Ryu connection...")

    if test_ryu():
        logging.info("Ryu server is reachable.")
    else:
        logging.warning(
            "Ryu server could not be verified."
        )

    logging.info("------------------------------------------")
    logging.info("Bridge is ready.")
    logging.info(
        "Call process_message() with Pocket Option "
        "WebSocket messages."
    )
    logging.info("------------------------------------------")

    # Uncomment ONLY for a one-tick connectivity test:
    #
    # demo_test()

    # Keep process alive.
    while True:
        time.sleep(30)

        logging.info(
            "BRIDGE ALIVE | tracked assets=%d",
            len(last_price)
        )


if __name__ == "__main__":
    main()
