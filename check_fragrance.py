import os
import re
import sys
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Official name confirmed via Selfridges email: "The Fragrance Haul advent calendar"
# Confirmed launch date: 8 October 2026. Confirmed teaser: /GB/en/inspiration/beauty-coming-soon/

WATCH_PAGES = [
    "https://www.selfridges.com/GB/en/cat/beauty/fragrance/",
    "https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/beauty/",
    "https://www.selfridges.com/GB/en/inspiration/beauty-coming-soon/",
    "https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/",
]

DEDICATED_CATEGORY_URL = "https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/fragrance/"

STATE_FILE = "fragrance_state.txt"

# Matches any Selfridges product URL whose slug contains "fragrance" together
# with "advent" or "haul" - covers whatever exact slug they launch with,
# e.g. selfridges-the-fragrance-haul-advent-calendar-2026_R0xxxxxxx
PRODUCT_LINK_RE = re.compile(
    r'https://www\.selfridges\.com/GB/en/product/([a-z0-9\-]+)_([A-Za-z0-9\-]+)/?'
)


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


def fetch(url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        return resp.status_code, resp.text
    except Exception as exc:
        print(f"Error fetching {url}: {exc}", file=sys.stderr)
        return None, ""


def find_fragrance_product_link(html: str):
    """Return the first product URL whose slug looks like the fragrance
    advent calendar, or None."""
    for match in PRODUCT_LINK_RE.finditer(html):
        slug = match.group(1).lower()
        if "fragrance" in slug and ("advent" in slug or "haul" in slug):
            return match.group(0)
    return None


def check_dedicated_category_page():
    status, _ = fetch(DEDICATED_CATEGORY_URL)
    if status == 200:
        return DEDICATED_CATEGORY_URL
    return None


def check_watch_pages():
    for url in WATCH_PAGES:
        status, html = fetch(url)
        if status != 200:
            continue
        link = find_fragrance_product_link(html)
        if link:
            return link
    return None


def main():
    found_link = check_watch_pages()
    if not found_link:
        found_link = check_dedicated_category_page()

    current_state = "FOUND" if found_link else "NOT_FOUND"

    previous_state = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            previous_state = f.read().strip()

    print(f"Current state: {current_state} (previous: {previous_state})")
    if found_link:
        print(f"Link: {found_link}")

    if current_state == "FOUND" and previous_state != "FOUND":
        send_telegram(
            "🌸🚨 THE FRAGRANCE HAUL ADVENT CALENDAR IS LIVE! 🚨🌸\n\n"
            f"{found_link}\n\n"
            "Go buy it now!"
        )

    with open(STATE_FILE, "w") as f:
        f.write(current_state)


if __name__ == "__main__":
    main()
