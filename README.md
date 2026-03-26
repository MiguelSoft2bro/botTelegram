# OpenCode Telegram Bridge

Control OpenCode from your phone via Telegram. Send messages, receive responses, and get notifications when tasks complete.

## Features

- Send messages to OpenCode from Telegram
- See TUI activity on your phone (bidirectional sync)
- Push notifications when OpenCode responds
- Multiple OpenCode sessions with dynamic ports
- Secure: only allowed user IDs can interact
- Send Telegram voice notes – they get transcribed with Whisper and forwarded to OpenCode
- Share Telegram photos – images are stored locally and announced to the OpenCode session

## Quick Install

```bash
git clone https://github.com/MiguelSoft2bro/botTelegram.git
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

Optional:

- `WHISPER_MODEL=base` (o el modelo de Whisper que prefieras) para controlar la calidad/velocidad de la transcripción.

### 5. Add shell function + watchdog

Add this block to tu `~/.zshrc` (ajusta las rutas si moviste el repo):

```bash
# OpenCode Telegram Bridge helpers
BRIDGE_BASE="$HOME/Desktop/TRABAJOS/phyton/bot"
BRIDGE_SCRIPT="$BRIDGE_BASE/bridge.py"
BRIDGE_PATTERN="bridge.py"
BRIDGE_WATCH="$BRIDGE_BASE/bridge_watch.sh"

start_bridge_if_needed() {
    if ! pgrep -f "$BRIDGE_PATTERN" >/dev/null; then
        (
            cd "$BRIDGE_BASE" &&
            nohup python3 "$BRIDGE_SCRIPT" >/tmp/bridge.log 2>&1 &
        )
    fi
}

ensure_bridge_watchdog() {
    if [ -x "$BRIDGE_WATCH" ] && ! pgrep -f "$BRIDGE_WATCH" >/dev/null; then
        nohup zsh "$BRIDGE_WATCH" >/tmp/bridge-watch.log 2>&1 &
    fi
}

cleanup_bridge_if_needed() {
    if ! pgrep -f "opencode --port" >/dev/null && pgrep -f "$BRIDGE_PATTERN" >/dev/null; then
        pkill -f "$BRIDGE_PATTERN"
    fi
}

opencode() {
    local port=4096
    while lsof -i :$port &>/dev/null; do
        ((port++))
    done

    start_bridge_if_needed
    ensure_bridge_watchdog

    echo "OpenCode starting on port $port"
    command opencode --port $port "$@"

    cleanup_bridge_if_needed
}
```

Then:

```bash
chmod +x $HOME/Desktop/TRABAJOS/phyton/bot/bridge_watch.sh
source ~/.zshrc
```

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
| `/start` | List active OpenCode instances (with connect buttons) |
| `/connect <session_id>` | Connect to a session |
| `/exit` | Disconnect from current session |
| `/sessions` | List all sessions on connected port |
| `/chatid` | Show current chat ID (for group setup) |

### Voice Notes (Whisper)

- Instala `ffmpeg` en tu sistema (requerido por Whisper) y asegúrate de correr `pip install -r requirements.txt` para tener `openai-whisper`.
- Opcional: ajusta `WHISPER_MODEL` en tu `.env` si querés otro tamaño (tiny/base/small/etc.).
- Envía una nota de voz o un audio: el bot la descarga, la transcribe con Whisper y la envía directo a OpenCode.
- Si algo falla (modelo no instalado, audio vacío, etc.), el bot te avisa en el chat.

### Images

- Las fotos que envías por Telegram se guardan en `bridge/uploads/` con un nombre único.
- El bot avisa a OpenCode de la ruta exacta, del tamaño y de la resolución. Desde la TUI puedes usar `Read` sobre esa ruta para inspeccionar la imagen.
- Si añades un pie de foto, se incluye en el mensaje que llega a OpenCode.
- Estos ficheros están gitignored para que no acaben en tu repo.

### Optional: Push Notifications Group

For reliable push notifications:

1. Create a Telegram group
2. Add your bot to the group
3. Send `/chatid` in the group
4. Add the ID to `.env` as `NOTIFICATION_GROUP_ID`

## Automatic Bridge Lifecycle

La instalación crea una función `opencode` y un watchdog `bridge_watch.sh` que se ocupan de arrancar y matar el bot automáticamente:

1. **Cuando ejecutas `opencode`**: se elige el siguiente puerto libre (4096+) y, si no hay bridge activo, se lanza `bridge.py`. También se arranca (una sola vez) `bridge_watch.sh` en segundo plano.
2. **Mientras haya sesiones**: el watchdog vigila que exista **solo un** `bridge.py`. Si el proceso muere, lo revive en segundos.
3. **Cuando la última sesión se cierra con `/exit`**: en cuanto ya no queda ningún `opencode --port`, el watchdog mata el bridge y se queda dormido.
4. **Tras reiniciar el equipo**: no queda nada corriendo. En cuanto vuelves a lanzar `opencode`, el ciclo arranca de nuevo (watchdog + bridge).

Si prefieres configurarlo a mano, revisa el fichero `bridge_watch.sh` y copia la función `opencode` del instalador para tu `~/.zshrc`. Solo necesitas actualizar las rutas si moviste el proyecto.

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
