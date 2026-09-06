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

# Candidate slugs the fragrance calendar's product URL is likely to contain,
# based on how the beauty calendar was named:
# selfridges-beauty-advent-calendar-2026-worth-1278_R04694469
FRAGRANCE_SLUG_PATTERNS = [
    "fragrance-advent-calendar",
    "fragrance-haul",
    "the-fragrance-haul",
]

# Pages to watch for the fragrance calendar appearing as a product tile.
WATCH_PAGES = [
    "https://www.selfridges.com/GB/en/cat/beauty/fragrance/",
    "https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/beauty/",
]

# A dedicated category page (parallel to the existing .../advent-calendars/food/
# page). It currently 404s. If it ever returns 200, that alone is a strong
# signal the fragrance calendar has launched.
DEDICATED_CATEGORY_URL = "https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/fragrance/"

STATE_FILE = "fragrance_state.txt"


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
        resp = requests.get(url, headers=HEADERS, timeout=30)
        return resp.status_code, resp.text
    except Exception as exc:
        print(f"Error fetching {url}: {exc}", file=sys.stderr)
        return None, ""


def check_dedicated_category_page() -> str | None:
    status, _ = fetch(DEDICATED_CATEGORY_URL)
    if status == 200:
        return DEDICATED_CATEGORY_URL
    return None


def check_watch_pages() -> str | None:
    for url in WATCH_PAGES:
        status, html = fetch(url)
        if status != 200:
            continue
        lower = html.lower()
        for pattern in FRAGRANCE_SLUG_PATTERNS:
            if pattern in lower:
                return f"{url} (matched: {pattern})"
    return None


def main():
    found_at = check_dedicated_category_page()
    if not found_at:
        found_at = check_watch_pages()

    current_state = "FOUND" if found_at else "NOT_FOUND"

    previous_state = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            previous_state = f.read().strip()

    print(f"Current state: {current_state} (previous: {previous_state})")
    if found_at:
        print(f"Signal detail: {found_at}")

    if current_state == "FOUND" and previous_state != "FOUND":
        send_telegram(
            "🌸 The Selfridges 2026 FRAGRANCE Advent Calendar looks like it's LIVE!\n\n"
            f"Signal: {found_at}\n\n"
            "Check https://www.selfridges.com/GB/en/cat/beauty/fragrance/ "
            "and https://www.selfridges.com/GB/en/cat/christmas-shop/advent-calendars/beauty/ "
            "right now!"
        )

    with open(STATE_FILE, "w") as f:
        f.write(current_state)


if __name__ == "__main__":
    main()
