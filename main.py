from flask import Flask, request, jsonify, render_template_string
import time
import os
import base64
import io

app = Flask(__name__)

# ============================================================
# RYU V2 STATE
# ============================================================

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
    "last_image": None,
    "image_received": False,
    "image_size": 0,
    "image_type": None,
}


# ============================================================
# DASHBOARD
# ============================================================

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

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

        .image-status {
            width: min(1000px, 94%);
            margin: 20px auto 40px;
            padding: 16px;
            background: #08150d;
            border: 1px solid #193a25;
            border-radius: 12px;
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

    <div class="subtitle">
        SIGNAL INTELLIGENCE DASHBOARD
    </div>

    <div id="feed" class="feed">
        Feed: DISCONNECTED
    </div>

</div>


<div class="grid">

    <div class="card">
        <div class="label">Asset</div>
        <div id="asset" class="value">
            EURUSD_otc
        </div>
    </div>


    <div class="card">
        <div class="label">Price</div>
        <div id="price" class="value">
            --
        </div>
    </div>


    <div class="card">
        <div class="label">Confidence</div>
        <div id="confidence" class="value">
            0%
        </div>
    </div>


    <div class="card signal">
        <div class="label">Signal</div>

        <div id="signal" class="value">
            WAIT
        </div>
    </div>


    <div class="card">
        <div class="label">Entry</div>

        <div id="entry" class="value">
            --
        </div>
    </div>


    <div class="card">
        <div class="label">Entry Window</div>

        <div id="entry_window" class="value">
            --
        </div>
    </div>


    <div class="card">
        <div class="label">Candles</div>

        <div id="candles" class="value">
            0
        </div>
    </div>

</div>


<button class="button" onclick="refreshSignal()">
    REFRESH SIGNAL
</button>


<div class="status">

    <div class="label">
        Live State
    </div>

    <div id="liveState" class="value">
        Waiting for feed...
    </div>

</div>


<div class="image-status">

    <div class="label">
        Screen Feed
    </div>

    <div id="imageState" class="value">
        No screenshot received
    </div>

</div>


<script>

async function refreshSignal() {

    try {

        const response = await fetch(
            "/api/state",
            {
                cache: "no-store"
            }
        );

        const data = await response.json();


        document.getElementById("asset").textContent =
            data.asset || "EURUSD_otc";


        document.getElementById("price").textContent =
            data.price !== null &&
            data.price !== undefined
                ? data.price
                : "--";


        document.getElementById("confidence").textContent =
            (data.confidence || 0) + "%";


        document.getElementById("signal").textContent =
            data.signal || "WAIT";


        document.getElementById("entry").textContent =
            data.entry !== null &&
            data.entry !== undefined
                ? data.entry
                : "--";


        document.getElementById("entry_window").textContent =
            data.entry_window
                ? data.entry_window + "s"
                : "--";


        document.getElementById("candles").textContent =
            data.candles || 0;


        const feed =
            document.getElementById("feed");

        const liveState =
            document.getElementById("liveState");


        if (data.feed === "LIVE") {

            feed.textContent =
                "Feed: LIVE";

            feed.className =
                "feed live";

            liveState.textContent =
                "LIVE";

            liveState.className =
                "value live";

        } else {

            feed.textContent =
                "Feed: DISCONNECTED";

            feed.className =
                "feed dead";

            liveState.textContent =
                "Waiting for feed...";

            liveState.className =
                "value dead";
        }


        const imageState =
            document.getElementById("imageState");


        if (data.image_received) {

            imageState.textContent =
                "Screenshot received (" +
                (data.image_size || 0) +
                " bytes)";

            imageState.className =
                "value live";

        } else {

            imageState.textContent =
                "No screenshot received";

            imageState.className =
                "value dead";
        }

    }

    catch (error) {

        document.getElementById("feed").textContent =
            "Feed: DISCONNECTED";

    }

}


refreshSignal();

setInterval(
    refreshSignal,
    1000
);

</script>

</body>
</html>
"""


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template_string(HTML)


# ============================================================
# STATE API
# ============================================================

@app.route("/api/state")
def api_state():

    # Disconnect if no feed update for 15 seconds.
    if STATE["last_update"]:

        age = time.time() - STATE["last_update"]

        if age > 15:

            STATE["feed"] = "DISCONNECTED"

    return jsonify(STATE)


# ============================================================
# JSON FEED
#
# Accepts:
#
# {
#   "asset": "EURUSD_otc",
#   "price": 1.2345,
#   "signal": "CALL",
#   "confidence": 85,
#   "entry": 1.2345,
#   "entry_window": 12,
#   "candles": 100
# }
# ============================================================

def process_json_feed(data):

    if not isinstance(data, dict):

        return False, "JSON must be an object"

    # Asset
    asset = (
        data.get("asset")
        or data.get("symbol")
        or data.get("pair")
    )

    if asset:

        STATE["asset"] = str(asset)


    # Price
    price = None

    if data.get("price") is not None:

        price = data.get("price")

    elif data.get("close") is not None:

        price = data.get("close")


    if price is not None:

        STATE["price"] = price


    # Candles
    candles = data.get("candles")

    if candles is not None:

        try:

            STATE["candles"] = int(candles)

        except (ValueError, TypeError):

            pass


    # Signal
    if data.get("signal") is not None:

        STATE["signal"] = (
            str(data["signal"]).upper()
        )


    # Confidence
    if data.get("confidence") is not None:

        try:

            confidence = int(
                float(data["confidence"])
            )

            # Keep confidence between 0 and 100.
            confidence = max(
                0,
                min(100, confidence)
            )

            STATE["confidence"] = confidence

        except (ValueError, TypeError):

            pass


    # Entry
    if data.get("entry") is not None:

        STATE["entry"] = data["entry"]


    # Entry window
    if data.get("entry_window") is not None:

        try:

            STATE["entry_window"] = int(
                float(data["entry_window"])
            )

        except (ValueError, TypeError):

            pass


    # Feed is alive.
    STATE["feed"] = "LIVE"

    STATE["last_update"] = time.time()


    return True, "JSON feed accepted"


# ============================================================
# SCREENSHOT STORAGE
#
# We accept:
#
# 1. multipart/form-data:
#       image=<file>
#       screenshot=<file>
#       frame=<file>
#
# 2. raw image body:
#       Content-Type: image/jpeg
#       Content-Type: image/png
#
# 3. JSON containing base64 image:
#       {
#           "image": "base64..."
#       }
# ============================================================

def process_image(image_bytes, content_type=None):

    if not image_bytes:

        return False, "Empty image"


    # Basic sanity check.
    if len(image_bytes) < 100:

        return False, "Image is too small"


    # Keep only the latest screenshot in memory.
    #
    # This does NOT write screenshots permanently
    # to the Render filesystem.
    #
    # Render's free filesystem should not be used
    # as permanent storage.
    STATE["last_image"] = base64.b64encode(
        image_bytes
    ).decode("ascii")


    STATE["image_received"] = True

    STATE["image_size"] = len(image_bytes)

    STATE["image_type"] = (
        content_type or "image/unknown"
    )


    # A screenshot is also proof that the
    # screen feed is alive.
    STATE["feed"] = "LIVE"

    STATE["last_update"] = time.time()


    return True, "Screenshot accepted"


# ============================================================
# FEED ENDPOINT
#
# This is the important part.
#
# It accepts JSON OR image uploads.
# ============================================================

@app.route(
    "/api/feed",
    methods=["POST"]
)
def api_feed():

    try:

        # ----------------------------------------------------
        # METHOD 1: JSON
        # ----------------------------------------------------

        if request.is_json:

            data = request.get_json(
                silent=True
            )

            if data:

                ok, message = process_json_feed(
                    data
                )

                if ok:

                    return jsonify({
                        "ok": True,
                        "type": "json",
                        "message": message,
                        "state": STATE
                    })

                return jsonify({
                    "ok": False,
                    "error": message
                }), 400


        # ----------------------------------------------------
        # METHOD 2: MULTIPART FILE UPLOAD
        # ----------------------------------------------------

        possible_names = [
            "image",
            "screenshot",
            "frame",
            "file",
            "photo"
        ]


        for name in possible_names:

            uploaded = request.files.get(name)

            if uploaded:

                image_bytes = uploaded.read()

                ok, message = process_image(
                    image_bytes,
                    uploaded.mimetype
                )

                if ok:

                    # Optional metadata can accompany
                    # the screenshot.
                    metadata = {}


                    asset = (
                        request.form.get("asset")
                        or request.form.get("symbol")
                        or request.form.get("pair")
                    )

                    if asset:

                        STATE["asset"] = str(asset)

                        metadata["asset"] = str(asset)


                    signal = request.form.get(
                        "signal"
                    )

                    if signal:

                        STATE["signal"] = (
                            signal.upper()
                        )


                    confidence = request.form.get(
                        "confidence"
                    )

                    if confidence:

                        try:

                            STATE["confidence"] = max(
                                0,
                                min(
                                    100,
                                    int(float(confidence))
                                )
                            )

                        except (
                            ValueError,
                            TypeError
                        ):

                            pass


                    return jsonify({
                        "ok": True,
                        "type": "image",
                        "message": message,
                        "bytes": len(image_bytes),
                        "state": STATE
                    })


                return jsonify({
                    "ok": False,
                    "error": message
                }), 400


        # ----------------------------------------------------
        # METHOD 3: RAW IMAGE BODY
        #
        # Example:
        #
        # Content-Type: image/jpeg
        #
        # body = JPEG bytes
        # ----------------------------------------------------

        content_type = (
            request.content_type or ""
        ).lower()


        if (
            content_type.startswith("image/")
            or request.data
        ):

            image_bytes = request.get_data(
                cache=False
            )


            if image_bytes:

                ok, message = process_image(
                    image_bytes,
                    request.content_type
                )


                if ok:

                    return jsonify({
                        "ok": True,
                        "type": "raw_image",
                        "message": message,
                        "bytes": len(image_bytes),
                        "state": STATE
                    })


        # ----------------------------------------------------
        # METHOD 4: FORM DATA WITHOUT FILE
        #
        # Some bridges send regular form fields.
        # ----------------------------------------------------

        if request.form:

            data = request.form.to_dict()

            ok, message = process_json_feed(
                data
            )


            if ok:

                return jsonify({
                    "ok": True,
                    "type": "form",
                    "message": message,
                    "state": STATE
                })


        # ----------------------------------------------------
        # NOTHING USABLE RECEIVED
        # ----------------------------------------------------

        return jsonify({
            "ok": False,
            "error": "No JSON or image data received",
            "content_type": request.content_type,
            "content_length": request.content_length,
            "files": list(request.files.keys()),
            "form_fields": list(request.form.keys())
        }), 400


    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ============================================================
# DEDICATED IMAGE ENDPOINT
#
# The bridge can also POST screenshots here.
#
# /api/screenshot
# /api/image
# /api/frame
# ============================================================

@app.route(
    "/api/screenshot",
    methods=["POST"]
)
@app.route(
    "/api/image",
    methods=["POST"]
)
@app.route(
    "/api/frame",
    methods=["POST"]
)
def api_screenshot():

    try:

        # Multipart upload.
        for name in [
            "image",
            "screenshot",
            "frame",
            "file",
            "photo"
        ]:

            uploaded = request.files.get(name)

            if uploaded:

                image_bytes = uploaded.read()

                ok, message = process_image(
                    image_bytes,
                    uploaded.mimetype
                )

                if ok:

                    return jsonify({
                        "ok": True,
                        "type": "image",
                        "message": message,
                        "bytes": len(image_bytes)
                    })

                return jsonify({
                    "ok": False,
                    "error": message
                }), 400


        # Raw image.
        image_bytes = request.get_data(
            cache=False
        )


        if image_bytes:

            ok, message = process_image(
                image_bytes,
                request.content_type
            )

            if ok:

                return jsonify({
                    "ok": True,
                    "type": "raw_image",
                    "message": message,
                    "bytes": len(image_bytes)
                })


        # JSON base64 image.
        if request.is_json:

            data = request.get_json(
                silent=True
            ) or {}


            encoded = (
                data.get("image")
                or data.get("screenshot")
                or data.get("frame")
            )


            if encoded:

                # Handle optional:
                # data:image/jpeg;base64,...
                if "," in encoded:

                    encoded = encoded.split(
                        ",",
                        1
                    )[1]


                image_bytes = base64.b64decode(
                    encoded
                )


                ok, message = process_image(
                    image_bytes,
                    "image/base64"
                )


                if ok:

                    return jsonify({
                        "ok": True,
                        "type": "base64_image",
                        "message": message,
                        "bytes": len(image_bytes)
                    })


        return jsonify({
            "ok": False,
            "error": "No image received",
            "content_type": request.content_type
        }), 400


    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ============================================================
# IMAGE PREVIEW
#
# Allows us to verify that Ryu actually received
# the latest screenshot.
# ============================================================

@app.route("/api/latest-image")
def latest_image():

    if not STATE["last_image"]:

        return jsonify({
            "ok": False,
            "error": "No screenshot received yet"
        }), 404


    try:

        image_bytes = base64.b64decode(
            STATE["last_image"]
        )


        content_type = (
            STATE["image_type"]
            or "image/jpeg"
        )


        if content_type == "image/base64":

            content_type = "image/jpeg"


        return (
            image_bytes,
            200,
            {
                "Content-Type": content_type,
                "Cache-Control":
                    "no-store, no-cache, must-revalidate"
            }
        )


    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    age = None

    if STATE["last_update"]:

        age = round(
            time.time() -
            STATE["last_update"],
            2
        )


    return jsonify({
        "status": "ok",
        "service": "RYU V2",
        "feed": STATE["feed"],
        "last_update_age": age,
        "image_received":
            STATE["image_received"],
        "image_size":
            STATE["image_size"]
    })


# ============================================================
# TEST ENDPOINT
# ============================================================

@app.route("/api/test")
def api_test():

    return jsonify({
        "ok": True,
        "service": "RYU V2",
        "message":
            "Ryu API is online and accepting JSON + images"
    })


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )


    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
