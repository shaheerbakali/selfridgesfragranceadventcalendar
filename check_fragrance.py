"""Selfridges 'The Fragrance Haul' advent calendar watcher (Queue-it aware).

Flow on launch day:
  product URL -> (Cloudflare edge) -> Queue-it waiting room -> product page

We notify on Telegram when either:
  * QUEUE_OPEN   - the Queue-it page stops saying "queue will open ..."
  * PRODUCT_LIVE - the product page itself loads with a real "Add to bag"

Modes (env vars):
  LOOP_MINUTES  >0  -> keep checking every ~25s for that many minutes
                0   -> single check (used by the 15-minute baseline workflow)
  SEND_TEST=true    -> send a test Telegram message first
"""
import hashlib
import json
import os
import random
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
# Clean queue URL (no personal enqueue token - those are per-visitor and expire in minutes).
QUEUE_URL = "https://selfridges.queue-it.net/?c=selfridges&e=fragrancecalendar"

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
# "Add to bag" that is NOT the Selfridges+ subscription button ("Add to bag - £10.00")
ADD_TO_BAG_RE = re.compile(r"add to (?:bag|basket)(?!\s*[-\u2013\u2014]\s*[£$€])")

PROBLEM_THRESHOLD = 20  # consecutive unreadable checks before warning you


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
        except Exception as exc:  # network blip
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


def fingerprint(html):
    """Hash of the page with per-visit tokens/long ids stripped out."""
    text = html.lower()
    text = re.sub(r"[a-z0-9_\-\.%=&:/]{24,}", " ", text)
    text = re.sub(r"\d{5,}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def product_is_purchasable(html):
    lower = html.lower()
    if any(m in lower for m in OUT_OF_STOCK_MARKERS):
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
        "queue_hash": None,
        "note": "",
    }
    queue_target = None
    try:
        r = get(PRODUCT_URL, follow=False)
        status = r.status_code
        loc = r.headers.get("Location", "")
        if status in REDIRECT_CODES and "queue-it" not in loc.lower():
            # ordinary redirect (region/slug) - follow it fully
            r = get(PRODUCT_URL, follow=True)
            status = r.status_code
            loc = r.url if "queue-it" in r.url.lower() else ""
        info["product_status"] = status

        if "queue-it" in loc.lower():
            info["to_queue"] = True
            queue_target = loc
        elif status == 200:
            info["ok"] = True
            if product_is_purchasable(r.text):
                info["product_live"] = True
                return info
        else:
            info["note"] = f"product page status {status}"
    except Exception as exc:
        info["note"] = f"product fetch error: {type(exc).__name__}"

    try:
        q = get(queue_target or QUEUE_URL, follow=True)
        info["queue_status"] = q.status_code
        if q.status_code == 200:
            info["ok"] = True
            lower = q.text.lower()
            info["queue_valid"] = ("queue-it" in lower) or ("queueit" in lower)
            info["queue_pre"] = any(m in lower for m in PRE_QUEUE_MARKERS)
            info["queue_hash"] = fingerprint(q.text)
        else:
            info["note"] = (info["note"] + f" queue status {q.status_code}").strip()
    except Exception as exc:
        info["note"] = (info["note"] + f" queue fetch error: {type(exc).__name__}").strip()
    return info


# ------------------------------------------------------------- classification
def calibrate(state, info):
    """First time we can read the queue page, decide how to detect 'open'."""
    if state.get("mode") or not info["queue_valid"]:
        return
    state["mode"] = "marker" if info["queue_pre"] else "fingerprint"
    state["baseline_hash"] = info["queue_hash"]
    state["calibrated_at"] = now_iso()


def classify(info, state):
    if info["product_live"]:
        return "PRODUCT_LIVE"
    if info["queue_valid"]:
        mode = state.get("mode")
        if mode == "marker" and not info["queue_pre"]:
            return "QUEUE_OPEN"
        if mode == "fingerprint" and info["queue_hash"] != state.get("baseline_hash"):
            return "QUEUE_OPEN"
    return "WAITING"


def track_problems(state, info):
    unreadable = (not info["ok"]) or (
        not info["queue_valid"] and not info["product_live"]
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
        f"Join now: {PRODUCT_URL}\n"
        "(That link sends you straight into the Queue-it waiting room.)\n\n"
        f"Backup: {QUEUE_URL}"
    ),
    "PRODUCT_LIVE": (
        "🛒🌸 THE FRAGRANCE HAUL IS ON SALE (no queue detected)!\n\n"
        f"Buy now: {PRODUCT_URL}"
    ),
}


def maybe_send_armed(state, info):
    if state.get("armed_sent") or not state.get("mode"):
        return
    if state["mode"] == "marker":
        detail = (
            "I can read the 'queue will open' message on the Queue-it page, so I'll alert "
            "you the moment it disappears."
        )
    else:
        detail = (
            "I couldn't see the 'will open' text in the raw page, so I'm watching for ANY "
            "change to the queue page instead (less precise, could occasionally false-alarm)."
        )
    send_telegram(
        "👀 Fragrance Haul watcher armed.\n"
        f"Product page redirects to queue: {'yes' if info['to_queue'] else 'no'}\n"
        f"{detail}\n"
        "Checking roughly every 25 seconds."
    )
    state["armed_sent"] = True


def run_once(state, loop_mode):
    info = probe()
    track_problems(state, info)
    calibrate(state, info)
    if loop_mode:
        maybe_send_armed(state, info)

    result = classify(info, state)
    if result != "WAITING":
        # confirm with a second probe a few seconds later to avoid one-off glitches
        time.sleep(4)
        info2 = probe()
        result2 = classify(info2, state)
        noisy = (
            result == "QUEUE_OPEN"
            and state.get("mode") == "fingerprint"
            and info["queue_hash"] != info2["queue_hash"]
        )
        if result2 != result or noisy:
            result = "WAITING"

    print(
        f"[{now_iso()}] state={result} mode={state.get('mode')} "
        f"product={info['product_status']} to_queue={info['to_queue']} "
        f"queue={info['queue_status']} valid={info['queue_valid']} "
        f"pre={info['queue_pre']} note={info['note']!r}"
    )

    if result != "WAITING" and result not in state["alerted"]:
        send_telegram(MESSAGES[result])
        state["alerted"][result] = now_iso()
        save_state(state)
        if loop_mode:
            for i in (1, 2):
                time.sleep(45)
                send_telegram(f"🔔 Reminder {i}/2: {MESSAGES[result]}")
    return result


def main():
    try:
        loop_minutes = min(float(os.environ.get("LOOP_MINUTES", "0") or 0), 350)
    except ValueError:
        loop_minutes = 0

    if os.environ.get("SEND_TEST", "").lower() == "true":
        ok = send_telegram("✅ Test message from your Selfridges fragrance watcher.")
        print("Test message sent." if ok else "Test message FAILED.")

    state = load_state()

    if loop_minutes <= 0:
        run_once(state, loop_mode=False)
        save_state(state)
        return

    end = time.time() + loop_minutes * 60
    print(f"Loop mode: {loop_minutes:.0f} minutes")
    while True:
        run_once(state, loop_mode=True)
        save_state(state)
        if time.time() + 30 >= end:
            break
        time.sleep(random.uniform(18, 33))


if __name__ == "__main__":
    main()
