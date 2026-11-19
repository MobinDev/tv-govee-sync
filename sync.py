import json
import logging
import os
import signal
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tv-govee-sync")

TV_IP = os.getenv("TV_IP", "192.168.2.198").strip()
TV_PORT = os.getenv("TV_PORT", "8002").strip()
TV_URL = f"https://{TV_IP}:{TV_PORT}/api/v2/"
TV_TIMEOUT = float(os.getenv("TV_TIMEOUT", "4.0"))

GOVEE_API_URL = os.getenv(
    "GOVEE_API_URL", "https://openapi.api.govee.com/router/api/v1/device/control"
).strip()
GOVEE_API_KEY = os.getenv("GOVEE_API_KEY", "").strip()
GOVEE_AUTH_HEADER = os.getenv("GOVEE_AUTH_HEADER", "Govee-API-Key").strip()
GOVEE_SKU = os.getenv("GOVEE_SKU", "H6199").strip()
GOVEE_DEVICE_ID = os.getenv("GOVEE_DEVICE_ID", "19:17:D9:32:37:36:5E:84").strip()

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "10"))
HEARTBEAT_FILE = "/tmp/heartbeat"

# Allow self-signed certificate on local Samsung TV API (port 8002)
TV_SSL_CONTEXT = ssl.create_default_context()
TV_SSL_CONTEXT.check_hostname = False
TV_SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# Strict TLS verification for Govee cloud API
CLOUD_SSL_CONTEXT = ssl.create_default_context()

stop_event = threading.Event()


def handle_signal(signum, _frame):
    logger.info("Received signal %s, shutting down gracefully...", signum)
    stop_event.set()


def touch_heartbeat() -> None:
    try:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError as exc:
        logger.warning("Failed to update heartbeat file: %s", exc)


def get_tv_state() -> str:
    """Query Samsung TV local API. Returns 'on' only if PowerState == 'on', otherwise 'off'."""
    req = urllib.request.Request(TV_URL, method="GET")
    try:
        with urllib.request.urlopen(
            req, timeout=TV_TIMEOUT, context=TV_SSL_CONTEXT
        ) as resp:
            if resp.status != 200:
                logger.debug("TV returned HTTP %s -> treating as off", resp.status)
                return "off"
            data = json.loads(resp.read().decode("utf-8"))
            power_state = data.get("device", {}).get("PowerState", "off")
            return "on" if str(power_state).lower() == "on" else "off"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("TV unreachable or offline (%s) -> treating as off", exc)
        return "off"


def set_govee_power(turn_on: bool) -> bool:
    """Send powerSwitch command to Govee OpenAPI v1."""
    payload = {
        "requestId": f"tv-sync-{uuid.uuid4().hex[:12]}",
        "payload": {
            "sku": GOVEE_SKU,
            "device": GOVEE_DEVICE_ID,
            "capability": {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1 if turn_on else 0,
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        GOVEE_AUTH_HEADER: GOVEE_API_KEY,
    }
    req = urllib.request.Request(
        GOVEE_API_URL, data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(
            req, timeout=10.0, context=CLOUD_SSL_CONTEXT
        ) as resp:
            resp_body = resp.read().decode("utf-8")
            if resp.status != 200:
                logger.error("Govee API HTTP %s: %s", resp.status, resp_body)
                return False
            parsed = json.loads(resp_body)
            if parsed.get("code") not in (200, None):
                logger.error("Govee API error response: %s", resp_body)
                return False
            logger.info(
                "Govee power set to %s (SKU=%s, Device=%s)",
                "ON" if turn_on else "OFF",
                GOVEE_SKU,
                GOVEE_DEVICE_ID,
            )
            return True
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to call Govee API: %s", exc)
        return False


def main() -> None:
    if not GOVEE_API_KEY:
        logger.critical("GOVEE_API_KEY is not set. Exiting.")
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info(
        "Starting TV -> Govee sync (TV=%s, Interval=%ss)", TV_URL, POLL_INTERVAL
    )
    last_state: str | None = None

    while not stop_event.is_set():
        touch_heartbeat()
        current_state = get_tv_state()

        if current_state != last_state:
            logger.info("TV state changed: %s -> %s", last_state, current_state)
            if set_govee_power(current_state == "on"):
                last_state = current_state
            else:
                logger.warning("Will retry syncing state '%s' on next cycle", current_state)

        stop_event.wait(POLL_INTERVAL)

    logger.info("Service stopped.")


if __name__ == "__main__":
    main()
