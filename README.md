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

> Prerrequisitos: tener **OpenCode** instalado (el binario `opencode` debe funcionar), además de **FFmpeg** y la librería `openai-whisper` para procesar notas de voz.

```bash
git clone https://github.com/MiguelSoft2bro/botTelegram.git
cd botTelegram
chmod +x install.sh
./install.sh
```

El script abre un instalador interactivo en terminal (con menú y prompts). Desde la opción “Instalación completa” realiza automáticamente:

1. Verificación de requisitos.
2. Instalación de dependencias de Python (`python-telegram-bot`, `aiohttp`, `openai-whisper`, etc.).
3. Creación guiada del `.env` con tu `BOT_TOKEN`, `ALLOWED_USER_IDS`, `NOTIFICATION_GROUP_ID` y `WHISPER_MODEL`.
4. Configuración de la función `opencode()` en tu `~/.zshrc`/`~/.bashrc`, que:
   - Encuentra el siguiente puerto libre (4096+), arranca OpenCode ahí.
   - Arranca `bridge.py` solo si no había uno activo.
   - Mata el puente automáticamente cuando ya no quedan sesiones `opencode --port`.
5. Instalación de la skill “telegram-bridge” en OpenCode para poder decir “arranca el bot”.

Puedes usar el menú para ejecutar pasos individuales (p. ej., regenerar solo el `.env`). Al terminar, abre una terminal nueva (o ejecuta `source ~/.zshrc`) y lanza `opencode`: el puente se levantará y se apagará solo.

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

### 5. Add auto-start shell function

Si no quieres usar el instalador, copia este bloque a tu `~/.zshrc` (ajusta `BRIDGE_HOME` con la ruta real del repo):

```bash
BRIDGE_HOME="$HOME/Desktop/TRABAJOS/phyton/bot"   # cambia esto por la ruta real

opencode() {
    local port=4096
    while lsof -i :$port &>/dev/null; do
        ((port++))
    done

    if ! pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Arrancando Telegram bridge..."
        (
            cd "$BRIDGE_HOME" &&
            nohup python3 bridge.py >/tmp/bridge.log 2>&1 &
        )
    else
        echo "Telegram bridge ya estaba activo"
    fi

    echo "OpenCode starting on port $port"
    command opencode --port $port "$@"

    if ! pgrep -f "opencode --port" >/dev/null && pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Cerrando Telegram bridge (no quedan sesiones de OpenCode)"
        pkill -f "python3.*bridge.py"
    fi
}
```

Después ejecuta `source ~/.zshrc` (o abre una terminal nueva) y listo.

## Usage

### Start OpenCode with HTTP API

```bash
opencode  # Uses dynamic port (4096, 4097, etc.)
```

### Start the Telegram bot

Normalmente no hace falta: la función `opencode` lo arranca sola. Si quieres iniciarlo manualmente:

```bash
python3 bridge.py
```

También puedes decirle a OpenCode: "arranca el bot".

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

Con la función `opencode` instalada:

1. **Cada vez que ejecutas `opencode`**: busca un puerto libre, arranca OpenCode y se asegura de que `bridge.py` esté corriendo (sin duplicados).
2. **Durante la sesión**: puedes ver/mandar mensajes, notas de voz y fotos; el puente se mantiene activo.
3. **Cuando cierras la última sesión** (no quedan procesos `opencode --port`): la función mata el `bridge.py` automáticamente.
4. **Tras reiniciar tu equipo**: no queda nada en memoria; solo tienes que volver a correr `opencode` y todo se levanta solo.

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
