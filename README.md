# OpenCode Telegram Bridge

Control OpenCode from Telegram: send prompts, receive responses, forward voice notes, and share images.

## Current Installer Version

- **v1.5** (tracked in the `VERSION` file)

## Features

- Send Telegram text messages to OpenCode
- Receive OpenCode responses in Telegram
- List and connect to OpenCode sessions across dynamic ports
- Voice note transcription with Whisper
- Image forwarding (saved locally and announced to the OpenCode session)
- Access control via allowed Telegram user IDs
- Automatic bridge lifecycle through shell `opencode()` helper

## Requirements

- OpenCode installed and available as `opencode`
- Python 3 + pip3
- FFmpeg (required for Whisper audio transcription)

## Quick Install

```bash
git clone https://github.com/MiguelSoft2bro/botTelegram.git
cd botTelegram
chmod +x install.sh
./install.sh
```

The installer is interactive and supports menu-based setup.

From **Full installation**, it will:

1. Validate local prerequisites
2. Install Python dependencies
3. Create/update `.env`
4. Configure your shell `opencode()` helper for bridge auto-start/auto-stop
5. Install the `telegram-bridge` OpenCode skill

## Manual Install

If you prefer manual setup:

### 1) Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2) Create Telegram bot credentials

1. Open Telegram and talk to `@BotFather`
2. Create a bot with `/newbot`
3. Copy the bot token
4. Get your Telegram user ID from `@userinfobot`

### 3) Configure `.env`

```bash
cp .env.example .env
```

Set values like:

```env
BOT_TOKEN=your_bot_token
ALLOWED_USER_IDS=your_telegram_user_id
NOTIFICATION_GROUP_ID=0
WHISPER_MODEL=base
```

### 4) Add shell helper (optional but recommended)

Add this to your `~/.zshrc` (or `~/.bashrc`) and adjust `BRIDGE_HOME`:

```bash
BRIDGE_HOME="$HOME/path/to/botTelegram"

opencode() {
    local port=4096
    while lsof -i :$port &>/dev/null; do
        ((port++))
    done

    if ! pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Starting Telegram bridge..."
        (
            cd "$BRIDGE_HOME" &&
            nohup python3 bridge.py >/tmp/bridge.log 2>&1 &
        )
    else
        echo "Telegram bridge already running"
    fi

    echo "OpenCode starting on port $port"
    command opencode --port $port "$@"

    if ! pgrep -f "opencode --port" >/dev/null && pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Stopping Telegram bridge (no OpenCode sessions left)"
        pkill -f "python3.*bridge.py"
    fi
}
```

Then reload your shell:

```bash
source ~/.zshrc
```

## Usage

### Start OpenCode

```bash
opencode
```

### Start bridge manually (if not using shell helper)

```bash
python3 bridge.py
```

### Telegram commands

| Command | Description |
|---|---|
| `/start` | Show active OpenCode instances and quick connect options |
| `/sessions` | List available sessions |
| `/connect <session_id>` | Connect Telegram chat to a session |
| `/exit` | Disconnect current Telegram ↔ OpenCode session |
| `/chatid` | Show current chat ID |

## Voice Notes (Whisper)

- Install FFmpeg on your system
- Keep `openai-whisper` installed from `requirements.txt`
- Optional: tune `WHISPER_MODEL` in `.env`

When a voice message is received, the bridge transcribes it and forwards text to OpenCode.

## Images

- Telegram photos/images are saved under `bridge/uploads/`
- The bridge sends OpenCode a message with file path, size, and resolution
- You can inspect the saved file from your OpenCode session

## Automatic Bridge Lifecycle

With the `opencode()` helper configured:

1. Starting `opencode` ensures the bridge is running
2. Messaging, voice, and image forwarding work while sessions are active
3. When all `opencode --port` sessions are closed, the bridge process is stopped

## Security

- Only IDs in `ALLOWED_USER_IDS` can use the bot
- Secrets are stored in `.env` (gitignored)

## License

MIT
