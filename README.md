# OpenCode Telegram Bridge

Control OpenCode from your phone via Telegram. Send messages, receive responses, and get notifications when tasks complete.

## Features

- Send messages to OpenCode from Telegram
- See TUI activity on your phone (bidirectional sync)
- Push notifications when OpenCode responds
- Multiple OpenCode sessions with dynamic ports
- Secure: only allowed user IDs can interact

## Quick Install

```bash
git clone <your-repo-url>
cd bot
chmod +x install.sh
./install.sh
```

The installer will:
1. Install Python dependencies
2. Guide you through creating a Telegram bot
3. Configure your `.env` file
4. Set up the `opencode` shell function for dynamic ports
5. Install the OpenCode skill

## Manual Install

> ⚠️ **Nota**: Si usaste `./install.sh`, esto ya está hecho. Esta sección es solo si prefieres instalar manualmente.

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a **name** for your bot (e.g., "My OpenCode Bot")
4. Choose a **username** (must end in `bot`, e.g., `myopencode_bot`)
5. BotFather will give you a **token** like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
6. Copy and save this token - you'll need it for `.env`

![BotFather example](https://core.telegram.org/file/811140327/1/zlN4goPTupk/9ff2f2f01c4bd1b013)

### 3. Get your User ID

1. Search for `@userinfobot` in Telegram
2. Send `/start`
3. The bot will reply with your info - copy the **Id** number (e.g., `429591886`)
4. This ID goes in `ALLOWED_USER_IDS` in your `.env`

> ⚠️ **Security**: Only user IDs in `ALLOWED_USER_IDS` can control your bot. Never share your bot token!

### 4. Configure

```bash
cp .env.example .env
# Edit .env with your values
```

### 5. Add shell function

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
opencode() {
    local port=4096
    while lsof -i :$port &>/dev/null; do
        ((port++))
    done
    echo "OpenCode starting on port $port"
    command opencode --port $port "$@"
}
```

Then: `source ~/.zshrc`

## Usage

### Start OpenCode with HTTP API

```bash
opencode  # Uses dynamic port (4096, 4097, etc.)
```

### Start the Telegram bot

```bash
python3 bridge.py
```

Or tell OpenCode: "arranca el bot"

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show status and help |
| `/ports` | List active OpenCode instances (with connect buttons) |
| `/connect <session_id>` | Connect to a session |
| `/disconnect` | Disconnect from current session |
| `/sessions` | List all sessions on connected port |
| `/chatid` | Show current chat ID (for group setup) |

### Optional: Push Notifications Group

For reliable push notifications:

1. Create a Telegram group
2. Add your bot to the group
3. Send `/chatid` in the group
4. Add the ID to `.env` as `NOTIFICATION_GROUP_ID`

## Architecture

```
+-------------+     +-------------+     +-------------+
|  Telegram   |<--->|  bridge.py  |<--->|  OpenCode   |
|   (Phone)   |     |  (Python)   |     | (HTTP API)  |
+-------------+     +-------------+     +-------------+
                          |
                          v
                    +-------------+
                    |    TUI      |
                    |    (PC)     |
                    +-------------+
```

## Security

- Only user IDs in `ALLOWED_USER_IDS` can interact with the bot
- Bot token stored in `.env` (gitignored)
- All commands go through OpenCode's safety layer

## License

MIT
