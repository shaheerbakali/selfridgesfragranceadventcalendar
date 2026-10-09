"""Selfridges 'The Fragrance Haul' advent calendar watcher (Queue-it aware).

Flow:
  product URL -> (sometimes) Queue-it waiting room -> product page
  product page can also show "Out of stock" / "more stock coming soon"

We notify on Telegram when any of these happen:
  * QUEUE_OPEN   - the Queue-it page stops saying "queue will open ..."
  * RESTOCKED    - the "more stock coming soon" banner clears (seen it before, now gone)
  * PRODUCT_LIVE - the product page loads with a real, clickable "Add to bag"

This is the SUSTAINED watcher: checks every 5 minutes (GitHub Actions' real
minimum), running continuously for a 3-week window from first deploy. It is
NOT meant to win a sub-minute flash-restock race - nothing legitimate can.
It IS meant to reliably catch a real batch restock that stays up for minutes,
which is what multi-restock products (like the beauty calendar) typically do.

Env vars:
  SEND_TEST=true    -> send a test Telegram message first
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

PRODUCT_URL = (
    "https://www.selfridges.com/GB/en/product/"
    "selfridges-fragrance-advent-calendar-2026-worth-1416_R04697805/"
)
QUEUE_URL = "https://selfridges.queue-it.net/?c=selfridges&e=fragrancecalendar"

# 3-week watch window. Edit this line to extend it.
WATCH_UNTIL = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)

STATE_FILE = "fragrance_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

REDIRECT_CODES = (301, 302, 303, 307, 308)
PRE_QUEUE_MARKERS = ("will open", "opens on", "opening on", "not open yet", "not yet open")
OUT_OF_STOCK_MARKERS = ("out of stock", "currently unavailable")
RESTOCK_PENDING_MARKERS = ("now unavailable", "more stock coming soon")
# "Add to bag" that is NOT the Selfridges+ subscription button ("Add to bag - £10.00")
ADD_TO_BAG_RE = re.compile(r"add to (?:bag|basket)(?!\s*[-–—]\s*[£$€])")

PROBLEM_THRESHOLD = 10  # consecutive unreadable checks before warning you
CONFIRM_DELAY_SECONDS = 5  # second probe this many seconds later, before alerting


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------- telegram
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram not configured] " + message)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for _ in range(3):
        try:
            r = requests.post(
                url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15
            )
            if r.ok:
                return True
            print(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            print(f"Telegram error: {type(exc).__name__}")
        time.sleep(2)
    return False


# ------------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("alerted", {})
    state.setdefault("problems_in_row", 0)
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ------------------------------------------------------------------ probing
def get(url, follow):
    return requests.get(url, headers=HEADERS, timeout=15, allow_redirects=follow)


def product_is_purchasable(html):
    lower = html.lower()
    if any(m in lower for m in OUT_OF_STOCK_MARKERS):
        return False
    if any(m in lower for m in RESTOCK_PENDING_MARKERS):
        return False
    return bool(ADD_TO_BAG_RE.search(lower))


def probe():
    info = {
        "ok": False,
        "product_status": None,
        "to_queue": False,
        "product_live": False,
        "queue_status": None,
        "queue_valid": False,
        "queue_pre": False,
        "restock_pending": False,
        "note": "",
    }
    product_html = None
    queue_html = None
    queue_target = None
    try:
        r = get(PRODUCT_URL, follow=False)
        status = r.status_code
        loc = r.headers.get("Location", "")
        if status in REDIRECT_CODES and "queue-it" not in loc.lower():
            r = get(PRODUCT_URL, follow=True)
            status = r.status_code
            loc = r.url if "queue-it" in r.url.lower() else ""
        info["product_status"] = status

        if "queue-it" in loc.lower():
            info["to_queue"] = True
            queue_target = loc
        elif status == 200:
            info["ok"] = True
            product_html = r.text
            if product_is_purchasable(product_html):
                info["product_live"] = True
        else:
            info["note"] = f"product page status {status}"
    except Exception as exc:
        info["note"] = f"product fetch error: {type(exc).__name__}"

    if not info["product_live"]:
        try:
            q = get(queue_target or QUEUE_URL, follow=True)
            info["queue_status"] = q.status_code
            if q.status_code == 200:
                info["ok"] = True
                queue_html = q.text
                lower = queue_html.lower()
                info["queue_valid"] = ("queue-it" in lower) or ("queueit" in lower)
                info["queue_pre"] = any(m in lower for m in PRE_QUEUE_MARKERS)
            else:
                info["note"] = (info["note"] + f" queue status {q.status_code}").strip()
        except Exception as exc:
            info["note"] = (
                info["note"] + f" queue fetch error: {type(exc).__name__}"
            ).strip()

    combined = " ".join(h.lower() for h in (product_html, queue_html) if h)
    info["restock_pending"] = any(m in combined for m in RESTOCK_PENDING_MARKERS)
    return info


# ------------------------------------------------------------- classification
def calibrate(state, info):
    if state.get("mode") or not info["queue_valid"]:
        return
    state["mode"] = "marker" if info["queue_pre"] else "fingerprint"
    state["calibrated_at"] = now_iso()


def classify(info, state):
    if info["product_live"]:
        return "PRODUCT_LIVE"
    if (
        state.get("restock_ever_seen")
        and not info["restock_pending"]
        and info["ok"]
        and not info["to_queue"]
    ):
        return "RESTOCKED"
    if info["queue_valid"] and state.get("mode") == "marker" and not info["queue_pre"]:
        return "QUEUE_OPEN"
    return "WAITING"


def track_problems(state, info):
    unreadable = (not info["ok"]) or (
        not info["queue_valid"] and not info["product_live"] and not info["restock_pending"]
    )
    if not unreadable:
        state["problems_in_row"] = 0
        state["problem_warned"] = False
        return
    state["problems_in_row"] = state.get("problems_in_row", 0) + 1
    if state["problems_in_row"] >= PROBLEM_THRESHOLD and not state.get("problem_warned"):
        send_telegram(
            "WARNING: the fragrance watcher can't read the Selfridges / Queue-it pages "
            f"(product status {info['product_status']}, queue status {info['queue_status']}, "
            f"{info['note'] or 'no queue-it markers found'}). It may be blocked or the page "
            "layout changed. Check the GitHub Actions logs."
        )
        state["problem_warned"] = True


MESSAGES = {
    "QUEUE_OPEN": (
        "🚨🌸 THE FRAGRANCE HAUL QUEUE IS OPEN! 🚨\n\n"
        f"Join now: {PRODUCT_URL}\n\n"
        f"Backup: {QUEUE_URL}"
    ),
    "PRODUCT_LIVE": (
        "🛒🌸 THE FRAGRANCE HAUL IS ON SALE!\n\n"
        f"Buy now: {PRODUCT_URL}"
    ),
    "RESTOCKED": (
        "🔥🌸 STOCK MIGHT BE BACK on The Fragrance Haul! 🔥\n\n"
        "The 'more stock coming soon' notice has cleared.\n\n"
        f"Go now: {PRODUCT_URL}\n"
        f"Queue link: {QUEUE_URL}\n\n"
        "Double-check it's real when you click through - this signal is a little "
        "looser than the others."
    ),
}


def run_once(state):
    info = probe()
    state["restock_ever_seen"] = state.get("restock_ever_seen", False) or info["restock_pending"]
    track_problems(state, info)
    calibrate(state, info)

    result = classify(info, state)
    if result != "WAITING":
        # confirm with a second probe before alerting, to avoid a one-off glitch
        time.sleep(CONFIRM_DELAY_SECONDS)
        info2 = probe()
        state["restock_ever_seen"] = state.get("restock_ever_seen", False) or info2["restock_pending"]
        result2 = classify(info2, state)
        if result2 != result:
            result = "WAITING"

    print(
        f"[{now_iso()}] state={result} mode={state.get('mode')} "
        f"product={info['product_status']} to_queue={info['to_queue']} "
        f"queue={info['queue_status']} valid={info['queue_valid']} "
        f"pre={info['queue_pre']} restock_pending={info['restock_pending']} "
        f"restock_ever_seen={state.get('restock_ever_seen')} note={info['note']!r}"
    )

    if result != "WAITING" and result not in state["alerted"]:
        send_telegram(MESSAGES[result])
        state["alerted"][result] = now_iso()
    return result


def main():
    if os.environ.get("SEND_TEST", "").lower() == "true":
        ok = send_telegram("✅ Test message from your Selfridges fragrance watcher.")
        print("Test message sent." if ok else "Test message FAILED.")

    now = datetime.now(timezone.utc)
    if now > WATCH_UNTIL:
        state = load_state()
        if not state.get("expiry_notice_sent"):
            send_telegram(
                "⏰ The Fragrance Haul watch window has ended (3 weeks elapsed) "
                "with no confirmed restock detected by this watcher. "
                "If you still want this, check the product page manually, or edit "
                "WATCH_UNTIL in check_fragrance.py to extend the window.\n\n"
                f"{PRODUCT_URL}"
            )
            state["expiry_notice_sent"] = True
            save_state(state)
        print(f"[{now_iso()}] watch window ended ({WATCH_UNTIL.date()}), skipping check.")
        return

    state = load_state()
    run_once(state)
    save_state(state)


if __name__ == "__main__":
    main()
