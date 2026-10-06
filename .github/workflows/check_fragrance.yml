name: Check Selfridges FRAGRANCE Advent Calendar

on:
  schedule:
    # Baseline safety net: one check every 15 minutes, all the time.
    # (GitHub's real minimum for cron is 5 minutes and runs can be delayed, so the
    # launch-day second-by-second watching is handled by launch_loop.yml instead.)
    - cron: "*/15 * * * *"
  workflow_dispatch:
    inputs:
      send_test:
        description: "Send a test Telegram message to confirm alerts work?"
        type: choice
        default: "false"
        options:
          - "false"
          - "true"

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Restore last known state
        uses: actions/cache/restore@v4
        with:
          path: fragrance_state.json
          key: fragrance-state-v3-${{ github.run_id }}
          restore-keys: |
            fragrance-state-v3-

      - name: Run fragrance check
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          SEND_TEST: ${{ inputs.send_test || 'false' }}
          LOOP_MINUTES: "0"
        run: python check_fragrance.py

      - name: Save state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: fragrance_state.json
          key: fragrance-state-v3-${{ github.run_id }}
