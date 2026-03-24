# Telegram Bridge — Manual E2E Validation Checklist

## Prerequisites

1. Python 3.10+ installed
2. `.env` file exists with valid `BOT_TOKEN` and `ALLOWED_USER_IDS`
3. Bot created via [@BotFather](https://t.me/BotFather); username known
4. Dependencies installed:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

---

## Step 1 — Launch the bot

```bash
# From project root
python bridge.py
```

**Expected output:**
```
============================================================
  Telegram Bridge — Session Ready
  Token : <22-char token>
  Link  : https://t.me/<bot_username>?start=<token>
============================================================
```

Also verify:
- `bridge/session.json` exists with `connected: false` and the generated token
- `bridge/inbox.json`, `bridge/outbox.json`, `bridge/state.json` exist
- `bridge/state.json` updates `last_heartbeat` every ~5s (run `cat bridge/state.json` repeatedly)

---

## Step 2 — Unauthorized rejection

1. From a **different** Telegram account (not user_id `429591886`), tap the deep link
2. **Expected**: Bot replies `⛔ Access denied. You are not authorized to use this bot.`
3. Verify `bridge/session.json` still has `connected: false`

---

## Step 3 — Invalid token rejection

1. From the authorized account, send `/start wrong_token` manually
2. **Expected**: Bot replies `❌ Invalid or expired token. Ask Claude to regenerate a new session link.`
3. Verify session is still not connected

---

## Step 4 — Successful connection

1. From the authorized account, tap the correct deep link (from Step 1 output)
2. **Expected**: Bot replies `✅ Connected! Bi-directional bridge is now active.`
3. Verify `bridge/session.json`:
   - `connected: true`
   - `chat_id` is populated
   - `user_id: 429591886`
   - `token: null` (consumed — one-time use)

---

## Step 5 — Telegram → Claude (inbox)

1. Send any text message from the authorized Telegram account
2. **Expected**: Message appears in `bridge/inbox.json`:
   ```json
   {"messages": [{"id": "msg_...", "text": "your message", "ts": 1711300000.0}]}
   ```
3. Claude reads inbox via filesystem Read tool and clears it

---

## Step 6 — Claude → Telegram (outbox)

1. Write a message to `bridge/outbox.json`:
   ```json
   {"messages": [{"id": "out_001", "text": "Hello from Claude!", "ts": 1711300001.0}]}
   ```
2. **Expected** (within 0.5s): Message delivered to Telegram chat

---

## Step 7 — Queued notification (pre-connect delivery)

1. Stop any running bot (`Ctrl+C`)
2. Restart: `python bridge.py`
3. **Before** tapping the new deep link, write a message to `outbox.json`
4. Now tap the deep link and connect
5. **Expected**: The queued message is delivered within 0.5s of connection

---

## Step 8 — Expired token

1. Stop the bot; manually edit `bridge/session.json` and set `created_at` to a timestamp > 10 minutes ago
2. Restart: `python bridge.py` (this generates a NEW token and overwrites session)
   - Alternatively: tap the stale deep link from a previous session
3. **Expected**: `❌ Invalid or expired token.`

---

## Step 9 — Reused token rejection

1. After successful connection (Step 4), try `/start <same_token>` again in Telegram
2. **Expected**: `❌ Invalid or expired token.` — token was consumed on first use

---

## Step 10 — Clean shutdown

1. Send `/stop` from the authorized Telegram account
2. **Expected**: Bot replies `🔌 Disconnected. Bridge session closed.`
3. Verify `bridge/session.json`:
   - `connected: false`
   - `chat_id: null`

---

## Automated Tests

Run the full test suite to verify all unit and integration scenarios:

```bash
source .venv/bin/activate
pytest tests/ -v
```

**Expected**: 29 tests pass in < 1s.
