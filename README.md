# Selfridges Advent Calendar Watcher

Checks the Selfridges "Coming Soon For 2026" beauty advent calendar page every
15 minutes and sends you a free Telegram message the moment it goes on sale.

Product page:
https://www.selfridges.com/GB/en/product/selfridges-coming-soon-for-2026_R04517782/

## How it works

- `check_stock.py` fetches the page and looks for a real "Add to bag" button
  for the product itself (ignoring the Selfridges+ delivery subscription
  buttons, which always say "Add to bag" even when the product is sold out).
- `.github/workflows/check.yml` runs that script on a schedule using GitHub
  Actions — completely free for this kind of usage.
- The last known state is cached between runs so you only get ONE alert, the
  moment it flips from out-of-stock to in-stock (not every 15 minutes forever).

## Setup (10 minutes, no coding required)

### 1. Create a free Telegram bot (for notifications)

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot` and follow the prompts (name it anything, e.g.
   `SelfridgesWatcherBot`).
3. BotFather gives you a **bot token** — looks like
   `123456789:ABCdefGhIJKlmNoPQRstuVwxYZ`. Save it.
4. Search for your new bot by its username and send it any message (e.g. "hi")
   — this is required so it's allowed to message you back.
5. Get your **chat ID**: open this URL in your browser (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Look for `"chat":{"id": 123456789, ...}` in the response — that number is
   your chat ID.

### 2. Create a GitHub repository

1. Go to https://github.com/new, create a new **private** repository (e.g.
   `selfridges-watcher`).
2. Upload all the files in this folder (`check_stock.py`, `requirements.txt`,
   `.github/workflows/check.yml`, this README) to that repo — either by
   dragging them into the GitHub web UI ("Add file" → "Upload files") or via
   git.

### 3. Add your Telegram credentials as GitHub Secrets

1. In your repo, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**, add:
   - Name: `TELEGRAM_BOT_TOKEN` — Value: the bot token from step 1.
   - Name: `TELEGRAM_CHAT_ID` — Value: your chat ID from step 1.

### 4. Turn it on

- Go to the **Actions** tab in your repo. If prompted, click "I understand my
  workflows, enable them."
- The workflow runs automatically every 15 minutes. You can also trigger it
  manually: Actions → "Check Selfridges Advent Calendar Stock" → "Run
  workflow" to test it immediately.

### 5. Test it

Run the workflow manually once (step above). Check the run logs — it should
print `Current state: OUT_OF_STOCK (previous: None)`. No Telegram message yet,
which is correct (nothing changed). The moment the page shows real stock, you
should get pinged.

## Notes

- Free GitHub accounts get 2,000 Actions minutes/month for private repos —
  this uses roughly 1 minute per run, ~96 runs/day = far under the limit.
- If Selfridges changes their page layout, the detection logic in
  `check_stock.py` may need a small tweak — ping me if that happens and I'll
  update it.
- You already have Unlocked early access, so this is really just a backstop
  in case the early-access email/notification is delayed or you miss it.
