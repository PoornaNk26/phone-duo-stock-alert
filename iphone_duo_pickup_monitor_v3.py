#!/usr/bin/env python3
"""Monitor Apple pickup availability for iPhone Duo 256GB Night Sky near ZIP 28027.

Uses Apple's public retail/pickup-message endpoint; does not use copied cookies.
Optional free push alerts via ntfy. Keep the script running and the Mac awake/online.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# IMPORTANT: Apple has been returning HTTP 541 for the older fulfillment-messages
# endpoint. The public pickup monitor project documents retail/pickup-message instead.
ENDPOINT = "https://www.apple.com/shop/retail/pickup-message"
PRODUCT_PART = "MK1F4LL/A"
PRODUCT_NAME = "iPhone Duo 256GB Night Sky"
ZIP_CODE = os.getenv("ZIP_CODE", "28027")
INTERVAL = max(60, int(os.getenv("INTERVAL", "60")))
NTFY_TOPIC = "duo_stock_poorna7mQ9vK2pL8nR4tW6zB3".strip()
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
PRODUCT_URL = "https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-256gb-night-sky-unlocked"


def log(message):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{stamp}] {message}", flush=True)


def fetch_stores():
    # This endpoint returns the nearest stores for a ZIP plus partsAvailability.
    # No cookies, browser session, or copied x-aos request token are needed.
    params = [
        ("pl", "true"),
        ("location", ZIP_CODE),
        ("parts.0", PRODUCT_PART),
    ]
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": PRODUCT_URL,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 541:
            raise RuntimeError(
                "Apple returned HTTP 541 for retail/pickup-message too. This is a blocked/unknown check, "
                "not evidence that the phone is out of stock. Stop and retry after a cooldown."
            ) from None
        raise RuntimeError(f"Apple pickup endpoint returned HTTP {exc.code}") from None

    stores = (data.get("body") or {}).get("stores")
    if stores is None:
        raise RuntimeError(
            "Unexpected Apple response shape: expected body.stores. Treating result as unknown, not out of stock."
        )
    if not stores:
        raise RuntimeError("Apple returned zero stores; treating result as unknown, not out of stock.")
    return stores


def send_alert(title, message):
    log(f"{title}:\n{message}")
    if not NTFY_TOPIC:
        log("No NTFY_TOPIC set; alerts are terminal-only for now.")
        return
    request = urllib.request.Request(
        f"{NTFY_SERVER}/{urllib.parse.quote(NTFY_TOPIC, safe='')}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": "urgent",
            "Tags": "iphone",
            "Click": PRODUCT_URL,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def check_once():
    stores = fetch_stores()
    available = {}
    for store in stores:
        store_name = store.get("storeName", "Unknown Apple Store")
        store_number = store.get("storeNumber", "unknown")
        address = store.get("address") or {}
        postal = address.get("postalCode", "")
        part_info = (store.get("partsAvailability") or {}).get(PRODUCT_PART) or {}
        # Explicit 'available' only. 'default', 'unavailable', or missing means no
        # confirmed pickup; endpoint/network errors are handled as UNKNOWN above.
        if part_info.get("pickupDisplay") == "available":
            label = f"{store_name} ({postal})" if postal else store_name
            available[store_number] = label
    log(f"Successful check: {len(stores)} stores returned near ZIP {ZIP_CODE}; confirmed available at {len(available)}.")
    return available


def main(once=False):
    previous = None
    while True:
        try:
            current = check_once()
            if previous is None:
                if current:
                    send_alert(f"{PRODUCT_NAME} pickup available", "Available at:\n" + "\n".join(current.values()))
                else:
                    log("Initial check: no confirmed pickup availability found.")
            else:
                newly_available = {k: v for k, v in current.items() if k not in previous}
                if newly_available:
                    send_alert(
                        f"{PRODUCT_NAME} pickup available!",
                        "Newly available at:\n" + "\n".join(newly_available.values()) + f"\n\n{PRODUCT_URL}",
                    )
                no_longer = {k: v for k, v in previous.items() if k not in current}
                if no_longer:
                    log("No longer listed as available: " + ", ".join(no_longer.values()))
            previous = current
        except Exception as exc:
            log(f"Check failed (availability UNKNOWN): {exc}")
        if once:
            return
        time.sleep(max(1, int(INTERVAL + random.uniform(-0.1, 0.1) * INTERVAL)))


if __name__ == "__main__":
    log(f"Starting {PRODUCT_NAME} pickup monitor for ZIP {ZIP_CODE}; polling every {INTERVAL}s.")
    main(once="--once" in sys.argv)
