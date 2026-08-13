import os
import re
import sys
import requests

PRODUCT_URL = "https://www.selfridges.com/GB/en/product/selfridges-coming-soon-for-2026_R04517782/"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

OUT_OF_STOCK_MARKERS = [
    "out of stock",
    "currently unavailable",
    "so sorry, this product is currently unavailable",
]

ADD_TO_BAG_MARKERS = [
    "add to bag",
    "add to basket",
]


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured; printing message instead:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    resp.raise_for_status()


def fetch_page() -> str:
    resp = requests.get(PRODUCT_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def is_in_stock(html: str) -> bool:
    lower = html.lower()

    has_out_of_stock_marker = any(marker in lower for marker in OUT_OF_STOCK_MARKERS)
    has_add_to_bag_for_product = False

    # Look for an "Add to bag" button that is NOT inside the Selfridges+ delivery
    # subscription section (that section always has its own "Add to bag - £10.00" /
    # "£75.00" buttons even while the product itself is out of stock).
    for marker in ADD_TO_BAG_MARKERS:
        idx = lower.find(marker)
        while idx != -1:
            snippet = lower[max(0, idx - 40): idx + 60]
            if "£10.00" not in snippet and "£75.00" not in snippet:
                has_add_to_bag_for_product = True
                break
            idx = lower.find(marker, idx + 1)
        if has_add_to_bag_for_product:
            break

    return has_add_to_bag_for_product and not has_out_of_stock_marker


def main():
    try:
        html = fetch_page()
    except Exception as exc:
        print(f"Error fetching page: {exc}", file=sys.stderr)
        # Don't alert on transient fetch errors, just exit non-zero for the Action log.
        sys.exit(1)

    in_stock = is_in_stock(html)

    state_file = "last_state.txt"
    previous_state = None
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            previous_state = f.read().strip()

    current_state = "IN_STOCK" if in_stock else "OUT_OF_STOCK"

    print(f"Current state: {current_state} (previous: {previous_state})")

    if current_state == "IN_STOCK" and previous_state != "IN_STOCK":
        send_telegram(
            "🎄 The Selfridges 2026 Beauty Advent Calendar looks like it's LIVE!\n\n"
            f"{PRODUCT_URL}\n\n"
            "Go grab it before it sells out!"
        )

    with open(state_file, "w") as f:
        f.write(current_state)


if __name__ == "__main__":
    main()
