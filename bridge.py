"""
Telegram Bridge — bridge.py
Bridge between Telegram and OpenCode CLI via `opencode run --attach` command execution.

Architecture: User → Telegram → Bot → opencode run --attach {url} -s {session_id} "message" → Response → Telegram
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ALLOWED_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}

# Optional: Notification group for push notifications of OpenCode responses
NOTIFICATION_GROUP_ID: int = int(os.getenv("NOTIFICATION_GROUP_ID", "0"))
WHISPER_MODEL_NAME: str = os.getenv("WHISPER_MODEL", "base")
_WHISPER_MODEL: Any | None = None

# Port range for scanning multiple OpenCode instances
OPENCODE_PORT_START: int = 4096
OPENCODE_PORT_END: int = 4106

BRIDGE_DIR = Path(__file__).parent / "bridge"
SESSION_PATH = BRIDGE_DIR / "session.json"
STATE_PATH = BRIDGE_DIR / "state.json"
UPLOADS_DIR = BRIDGE_DIR / "uploads"

MAX_MESSAGE_LEN = 4096  # Telegram character limit
COMMAND_TIMEOUT = 300  # 5 minutes max for opencode run
POLLING_INTERVAL = 2.5  # seconds between polls for new messages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bridge")


# ──────────────────────────────────────────────────────────────────────────────
# Whisper helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL

    try:
        import whisper  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in runtime
        raise RuntimeError(
            "Whisper no está instalado. Ejecuta 'pip install openai-whisper'."
        ) from exc

    _WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    return _WHISPER_MODEL


async def transcribe_audio_file(path: Path) -> str:
    """Transcribe *path* audio file using Whisper in a thread pool."""

    loop = asyncio.get_running_loop()

    def _transcribe() -> str:
        model = _load_whisper_model()
        result = model.transcribe(str(path))
        return (result.get("text") or "").strip()

    return await loop.run_in_executor(None, _transcribe)


# ──────────────────────────────────────────────────────────────────────────────
# Atomic JSON helpers
# ──────────────────────────────────────────────────────────────────────────────

def atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write *data* to *path* atomically (write tmp → os.replace)."""
    dir_name = path.parent
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Read JSON from *path*; return *default* on any read/parse error."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default)


# ──────────────────────────────────────────────────────────────────────────────
# JSON schemas
# ──────────────────────────────────────────────────────────────────────────────

EMPTY_SESSION: dict[str, Any] = {
    "chat_id": None,
    "user_id": None,
    "connected": False,
    "opencode_session_id": None,  # The opencode session ID to use
    "opencode_port": None,  # The port where this session is running
    "connected_at": None,
    "last_seen_message_id": None,  # Track last message to avoid duplicates in polling
}

EMPTY_STATE: dict[str, Any] = {
    "status": "idle",
    "last_heartbeat": None,
    "running_command": False,
}


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap — ensure bridge/ dir and JSON files exist
# ──────────────────────────────────────────────────────────────────────────────

def bootstrap() -> None:
    """Ensure runtime directory and all JSON schema files exist."""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    for path, schema in [
        (SESSION_PATH, EMPTY_SESSION),
        (STATE_PATH, EMPTY_STATE),
    ]:
        if not path.exists():
            atomic_write(path, schema)


# ──────────────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_session() -> dict[str, Any]:
    return safe_read(SESSION_PATH, dict(EMPTY_SESSION))


def save_session(session: dict[str, Any]) -> None:
    atomic_write(SESSION_PATH, session)


def connect_session(chat_id: int, user_id: int, opencode_session_id: str, port: int) -> None:
    """Connect to an opencode session on a specific port."""
    session = load_session()
    session["chat_id"] = chat_id
    session["user_id"] = user_id
    session["connected"] = True
    session["opencode_session_id"] = opencode_session_id
    session["opencode_port"] = port
    session["connected_at"] = time.time()
    session["last_seen_message_id"] = None  # Will be initialized after connect
    save_session(session)


def disconnect_session() -> None:
    """Clear connection state."""
    save_session(dict(EMPTY_SESSION))


def get_opencode_session_id() -> str | None:
    session = load_session()
    if session.get("connected"):
        return session.get("opencode_session_id")
    return None


def get_active_chat_id() -> int | None:
    session = load_session()
    if session.get("connected"):
        return session.get("chat_id")
    return None


def get_session_port() -> int | None:
    """Get the port of the currently connected session."""
    session = load_session()
    if session.get("connected"):
        return session.get("opencode_port")
    return None


def update_last_seen_message(message_id: str) -> None:
    """Update the last seen message ID for the current session."""
    session = load_session()
    session["last_seen_message_id"] = message_id
    save_session(session)


def check_port_accessible(port: int) -> bool:
    """Check if a specific port is accessible."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", port))
        sock.close()
        return result == 0
    except socket.error:
        return False


async def scan_opencode_ports() -> list[dict[str, Any]]:
    """
    Scan port range to find all running OpenCode instances and their sessions.
    Returns list of {port, sessions: [...], project: ...}
    """
    results = []
    
    async def check_port(port: int) -> dict[str, Any] | None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                async with session.get(f"http://localhost:{port}/session") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # API returns an array directly: [{"id":"ses_xxx", ...}, ...]
                        # NOT an object like {"sessions": [...]}
                        sessions = data if isinstance(data, list) else []
                        if sessions:
                            return {
                                "port": port,
                                "sessions": sessions,
                            }
        except Exception:
            pass
        return None
    
    # Scan all ports in parallel
    tasks = [check_port(port) for port in range(OPENCODE_PORT_START, OPENCODE_PORT_END + 1)]
    port_results = await asyncio.gather(*tasks)
    
    for result in port_results:
        if result:
            results.append(result)
    
    return results


async def find_session_port(session_id: str) -> int | None:
    """Find which port a specific session ID is running on."""
    instances = await scan_opencode_ports()
    for instance in instances:
        for sess in instance.get("sessions", []):
            if sess.get("id") == session_id:
                return instance["port"]
    return None


def check_opencode_port(port: int) -> tuple[bool, str]:
    """
    Check if the OpenCode TUI is accessible at the configured port.
    
    Returns:
        (True, message) if port is accessible
        (False, error_message) if port is not accessible
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("localhost", port))
        sock.close()
        
        if result == 0:
            return True, f"OpenCode TUI accessible at port {port}"
        else:
            return False, (
                f"Cannot connect to OpenCode TUI at port {port}.\n"
                f"Make sure OpenCode TUI is running with: opencode --port {port}"
            )
    except socket.error as e:
        return False, f"Socket error checking port {port}: {str(e)}"


async def fetch_session_messages(port: int, session_id: str) -> list[dict[str, Any]]:
    """
    Fetch messages from an OpenCode session.
    
    Returns list of messages with structure:
    {
        "id": "msg_xxx",
        "role": "user" | "assistant",
        "text": "message content",
        "created": timestamp,
        "parent_id": "msg_xxx" | None  # For assistant messages, the user message it replies to
    }
    """
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
            async with client.get(f"http://localhost:{port}/session/{session_id}/message") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                
                messages = []
                for msg in data:
                    info = msg.get("info", {})
                    role = info.get("role")
                    msg_id = info.get("id")
                    created = info.get("time", {}).get("created", 0)
                    parent_id = info.get("parentID")
                    
                    # Extract text from parts
                    text_parts = []
                    for part in msg.get("parts", []):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    
                    text = "\n".join(text_parts).strip()
                    
                    if role and msg_id and text:
                        messages.append({
                            "id": msg_id,
                            "role": role,
                            "text": text,
                            "created": created,
                            "parent_id": parent_id,
                        })
                
                return messages
    except Exception as e:
        logger.debug("Error fetching messages from port %s session %s: %s", port, session_id, e)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# OpenCode command execution
# ──────────────────────────────────────────────────────────────────────────────

async def run_opencode(session_id: str, message: str, port: int) -> tuple[bool, str]:
    """
    Execute `opencode run --attach {url} -s {session_id} "{message}"` and return (success, output).
    
    Uses --attach to connect to an existing TUI session instead of creating a new one.
    
    Returns:
        (True, output) on success
        (False, error_message) on failure
    """
    attach_url = f"http://localhost:{port}"
    # Build command with --attach for TUI session attachment
    cmd = ["opencode", "run", "--attach", attach_url, "-s", session_id, message]
    
    logger.info("Executing: opencode run --attach %s -s %s %s", 
                attach_url, session_id, shlex.quote(message[:50] + "..."))
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, f"Command timed out after {COMMAND_TIMEOUT} seconds"
        
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        
        if process.returncode == 0:
            return True, stdout_text
        else:
            error_msg = stderr_text or stdout_text or f"Command failed with exit code {process.returncode}"
            return False, error_msg
            
    except FileNotFoundError:
        return False, "opencode command not found. Is it installed and in PATH?"
    except Exception as e:
        logger.exception("Error running opencode: %s", e)
        return False, f"Error executing command: {str(e)}"


async def list_opencode_sessions() -> tuple[bool, str]:
    """
    Execute `opencode session list` and return (success, output).
    """
    cmd = ["opencode", "session", "list"]
    
    logger.info("Executing: opencode session list")
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30  # 30 seconds should be enough for listing
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, "Command timed out"
        
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        
        if process.returncode == 0:
            return True, stdout_text
        else:
            error_msg = stderr_text or stdout_text or f"Command failed with exit code {process.returncode}"
            return False, error_msg
            
    except FileNotFoundError:
        return False, "opencode command not found. Is it installed and in PATH?"
    except Exception as e:
        logger.exception("Error listing sessions: %s", e)
        return False, f"Error: {str(e)}"


# ──────────────────────────────────────────────────────────────────────────────
# Response helpers
# ──────────────────────────────────────────────────────────────────────────────

def truncate_response(text: str, max_len: int = MAX_MESSAGE_LEN) -> str:
    """Truncate text to fit Telegram's message limit."""
    if len(text) <= max_len:
        return text
    
    truncation_notice = "\n\n... [truncated, response too long]"
    available = max_len - len(truncation_notice)
    return text[:available] + truncation_notice


# ──────────────────────────────────────────────────────────────────────────────
# Telegram handlers
# ──────────────────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — show active OpenCode instances with their current session."""
    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    instances = await scan_opencode_ports()

    if not instances:
        await message.reply_text(
            f"No hay instancias de OpenCode activas.\n\n"
            f"Inicia OpenCode con: opencode"
        )
        return

    lines = ["🖥️ OpenCode activos:\n"]
    buttons = []

    for instance in instances:
        port = instance["port"]
        sessions_list = instance.get("sessions", [])

        first_sess = sessions_list[0] if sessions_list else {}
        path = first_sess.get("directory", first_sess.get("path", first_sess.get("working_directory", "")))
        project = Path(path).name if path else "unknown"

        current_session_id = first_sess.get("id", "unknown")
        short_id = current_session_id[:12] + "..." if len(current_session_id) > 12 else current_session_id

        lines.append(f"Port {port} → {project}")
        lines.append(f"  📍 {short_id}")
        lines.append("")

        button_text = f"🔗 {project} ({port})"
        callback_data = f"connect:{current_session_id}:{port}"
        buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))

    lines.append("Usa /connect <session_id> para conectarte.")
    response = "\n".join(lines)

    keyboard = []
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(truncate_response(response), reply_markup=reply_markup)


async def connect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/connect {session_id} — connect to an opencode session (auto-discovers port)."""
    user = update.effective_user
    chat = update.effective_chat
    message = update.message

    if user is None or chat is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "Usage: /connect <session_id>\n\n"
            "Use /sessions to list available sessions."
        )
        return

    session_id = args[0]
    
    # Find which port has this session
    await message.reply_text(f"Searching for session {session_id}...")
    
    port = await find_session_port(session_id)
    if not port:
        await message.reply_text(
            f"Session '{session_id}' not found on any port ({OPENCODE_PORT_START}-{OPENCODE_PORT_END}).\n\n"
            f"Use /sessions to see available sessions."
        )
        return
    
    # Connect to the session with the discovered port
    connect_session(chat.id, user.id, session_id, port)
    
    # Initialize last_seen_message_id to avoid sending historical messages
    messages = await fetch_session_messages(port, session_id)
    if messages:
        update_last_seen_message(messages[-1]["id"])
    
    logger.info("Connected to opencode session: user=%s session=%s port=%s", 
                user.id, session_id, port)
    
    await message.reply_text(
        f"Connected to session: {session_id}\n"
        f"OpenCode Port: {port}\n\n"
        f"Send messages to interact with OpenCode.\n"
        f"Use /exit to end the session."
    )


async def exit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/exit — disconnect from the current session."""
    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    session = load_session()
    if not session.get("connected"):
        await message.reply_text("Not connected to any session.")
        return

    old_session_id = session.get("opencode_session_id", "unknown")
    disconnect_session()
    logger.info("Disconnected from session %s by user %s", old_session_id, user.id)
    
    await message.reply_text(
        f"Disconnected from session: {old_session_id}\n\n"
        f"Use /connect <session_id> to connect to a new session."
    )


async def sessions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sessions — list available opencode sessions across all ports."""
    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    await message.reply_text(f"Scanning ports {OPENCODE_PORT_START}-{OPENCODE_PORT_END}...")
    
    instances = await scan_opencode_ports()
    
    if not instances:
        await message.reply_text(
            f"No OpenCode instances found on ports {OPENCODE_PORT_START}-{OPENCODE_PORT_END}.\n\n"
            f"Start OpenCode with: opencode"
        )
        return
    
    # Build response showing all sessions grouped by port
    lines = ["Sessions disponibles:\n"]
    for instance in instances:
        port = instance["port"]
        sessions_list = instance.get("sessions", [])
        
        # Get project name from first session's directory
        first_sess = sessions_list[0] if sessions_list else {}
        path = first_sess.get("directory", first_sess.get("path", first_sess.get("working_directory", "")))
        project = Path(path).name if path else "unknown"
        
        lines.append(f"📍 Port {port} ({project}):")
        for sess in sessions_list:
            sess_id = sess.get("id", "unknown")
            title = sess.get("title", "")
            if title:
                lines.append(f"  • {sess_id} - {title}")
            else:
                lines.append(f"  • {sess_id}")
        lines.append("")  # Empty line between ports
    
    response = "\n".join(lines)
    response += f"Usa /connect <session_id> para conectarte."
    
    await message.reply_text(truncate_response(response))


async def chatid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chatid — show the current chat ID."""
    chat = update.effective_chat
    message = update.message
    if chat and message:
        await message.reply_text(f"Chat ID: `{chat.id}`", parse_mode="Markdown")


async def connect_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks from /start command."""
    query = update.callback_query
    user = update.effective_user
    chat = update.effective_chat

    if query is None or user is None or chat is None:
        return

    await query.answer()

    if user.id not in ALLOWED_USER_IDS:
        await query.edit_message_text("Access denied.")
        return

    # Parse callback_data: "connect:{session_id}:{port}"
    if not query.data:
        await query.edit_message_text("Error: Invalid button data.")
        return

    try:
        _, session_id, port_str = query.data.split(":")
        port = int(port_str)
    except (ValueError, AttributeError):
        await query.edit_message_text("Error: Invalid button data.")
        return

    # Verify the session still exists
    found_port = await find_session_port(session_id)
    if not found_port:
        await query.edit_message_text(
            f"Session '{session_id}' not found.\n"
            f"The OpenCode instance may have been closed.\n\n"
            f"Use /start to see active instances."
        )
        return

    # Connect to the session
    connect_session(chat.id, user.id, session_id, found_port)
    
    # Initialize last_seen_message_id to avoid sending historical messages
    messages = await fetch_session_messages(found_port, session_id)
    if messages:
        update_last_seen_message(messages[-1]["id"])
    
    logger.info("Connected via button: user=%s session=%s port=%s", 
                user.id, session_id, found_port)

    # Truncate session ID for display
    short_id = session_id[:12] + "..." if len(session_id) > 12 else session_id

    await query.edit_message_text(
        f"✅ Conectado a sesión: {short_id}\n"
        f"📍 Port: {found_port}\n\n"
        f"Envía mensajes para interactuar con OpenCode.\n"
        f"Usa /exit para desconectar."
    )


async def execute_user_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Send *text* to the connected OpenCode session."""

    message = update.message
    if message is None:
        return

    session = load_session()
    if not session.get("connected"):
        await message.reply_text(
            "Not connected to any session.\n"
            "Use /connect <session_id> to connect first."
        )
        return

    session_id = session.get("opencode_session_id")
    port = session.get("opencode_port")

    if not session_id:
        await message.reply_text("Session ID not found. Please reconnect.")
        return

    if not port:
        port = await find_session_port(session_id)
        if port:
            session["opencode_port"] = port
            save_session(session)
        else:
            await message.reply_text(
                f"Session '{session_id}' not found. The OpenCode instance may have been closed.\n"
                f"Use /sessions to see available sessions."
            )
            return

    sanitized = text.strip()
    if not sanitized:
        await message.reply_text("Empty message. Try again.")
        return

    atomic_write(STATE_PATH, {
        "status": "running",
        "last_heartbeat": time.time(),
        "running_command": True,
    })

    chat = update.effective_chat
    if chat is not None:
        await chat.send_action("typing")

    thinking_msg = await message.reply_text("Processing...")

    try:
        success, output = await run_opencode(session_id, sanitized, port)

        if success:
            response = output.strip() if output.strip() else "(empty response)"
        else:
            response = f"Error:\n{output}"

        try:
            await thinking_msg.delete()
        except Exception:
            pass

        await message.reply_text(truncate_response(response))

        messages = await fetch_session_messages(port, session_id)
        if messages:
            update_last_seen_message(messages[-1]["id"])

        current_chat_id = chat.id if chat else None
        if (
            current_chat_id is not None
            and NOTIFICATION_GROUP_ID != 0
            and NOTIFICATION_GROUP_ID != current_chat_id
        ):
            try:
                notification = f"📬 Respuesta de OpenCode:\n\n{response}"
                await context.bot.send_message(
                    chat_id=NOTIFICATION_GROUP_ID,
                    text=truncate_response(notification),
                )
            except Exception as notif_err:
                logger.warning(
                    "Failed to send notification to group %s: %s",
                    NOTIFICATION_GROUP_ID,
                    notif_err,
                )

    except Exception as e:
        logger.exception("Error processing message: %s", e)
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await message.reply_text(f"Internal error: {str(e)}")

    finally:
        atomic_write(STATE_PATH, {
            "status": "waiting",
            "last_heartbeat": time.time(),
            "running_command": False,
        })


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages — send to OpenCode."""
    user = update.effective_user

    if user is None or update.message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("Access denied.")
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    await execute_user_prompt(update, context, text)


def format_file_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(num_bytes, 1))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram photos/documents, persist them, and notify OpenCode."""

    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    media = None
    resolution = None

    if message.photo:
        media = message.photo[-1]
        resolution = f"{media.width}x{media.height}"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        media = message.document

    if media is None:
        await message.reply_text("No se detectó una imagen válida.")
        return

    session = load_session()
    if not session.get("connected"):
        await message.reply_text(
            "Not connected to any session.\nUse /connect <session_id> to connect first."
        )
        return

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    telegram_file = await media.get_file()
    suffix_candidates = [
        Path(getattr(telegram_file, "file_path", "")).suffix,
        Path(getattr(media, "file_name", "") or "").suffix,
    ]
    extension = next((ext for ext in suffix_candidates if ext), ".jpg")

    timestamp = int(time.time())
    unique_id = getattr(media, "file_unique_id", getattr(media, "file_id", "photo"))
    filename = f"telegram_photo_{unique_id}_{timestamp}{extension}"
    destination = UPLOADS_DIR / filename

    await telegram_file.download_to_drive(custom_path=str(destination))

    size_label = format_file_size(destination.stat().st_size)
    caption = (message.caption or "").strip()

    note_lines = [
        "📸 Telegram photo received.",
        f"Saved path: {destination}",
        f"Size: {size_label}",
    ]
    if resolution:
        note_lines.append(f"Resolution: {resolution}")
    if caption:
        note_lines.append(f"Caption: {caption}")
    note_lines.append("Use the Read tool on that path if you need to inspect the file.")

    await execute_user_prompt(update, context, "\n".join(note_lines))


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice/audio messages: transcribe and forward to OpenCode."""
    user = update.effective_user
    message = update.message

    if user is None or message is None:
        return

    if user.id not in ALLOWED_USER_IDS:
        await message.reply_text("Access denied.")
        return

    media = message.voice or message.audio
    if media is None:
        await message.reply_text("No se detectó un audio válido.")
        return

    fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    temp_path = Path(tmp_path)

    try:
        telegram_file = await media.get_file()
        await telegram_file.download_to_drive(custom_path=str(temp_path))
        transcription = await transcribe_audio_file(temp_path)
    except RuntimeError as err:
        await message.reply_text(str(err))
        return
    except Exception as exc:
        logger.exception("Error processing voice message: %s", exc)
        await message.reply_text(f"No pude transcribir el audio: {exc}")
        return
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass

    if not transcription:
        await message.reply_text("No pude entender el audio. ¿Podés intentarlo de nuevo?")
        return

    await execute_user_prompt(update, context, transcription)


# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat
# ──────────────────────────────────────────────────────────────────────────────

async def heartbeat(app: Application) -> None:  # type: ignore[type-arg]
    """Async task: write state.json with current status every 5s."""
    logger.info("Heartbeat task started")
    while True:
        try:
            session = load_session()
            state = safe_read(STATE_PATH, dict(EMPTY_STATE))
            
            # Don't overwrite if a command is running
            if not state.get("running_command"):
                status = "waiting" if session.get("connected") else "idle"
                atomic_write(STATE_PATH, {
                    "status": status,
                    "last_heartbeat": time.time(),
                    "running_command": False,
                })
        except Exception as exc:
            logger.exception("Heartbeat error: %s", exc)
        await asyncio.sleep(5)


async def poll_opencode_messages(app: Application) -> None:  # type: ignore[type-arg]
    """
    Background task: Poll the connected OpenCode session for new messages.
    
    When a user types in the TUI on PC, the response will also be sent to Telegram.
    Only sends 'assistant' messages that are newer than the last seen message.
    
    Note: Messages sent FROM Telegram are handled by message_handler which updates
    last_seen_message_id after receiving the response, preventing duplicates.
    """
    logger.info("OpenCode message polling task started")
    
    while True:
        try:
            session = load_session()
            
            if not session.get("connected"):
                await asyncio.sleep(POLLING_INTERVAL)
                continue
            
            session_id = session.get("opencode_session_id")
            port = session.get("opencode_port")
            chat_id = session.get("chat_id")
            last_seen = session.get("last_seen_message_id")
            
            if not session_id or not port or not chat_id:
                await asyncio.sleep(POLLING_INTERVAL)
                continue
            
            # Skip if a command is currently running (Telegram is handling the response)
            state = safe_read(STATE_PATH, dict(EMPTY_STATE))
            if state.get("running_command"):
                await asyncio.sleep(POLLING_INTERVAL)
                continue
            
            # Fetch messages from OpenCode
            messages = await fetch_session_messages(port, session_id)
            
            if not messages:
                await asyncio.sleep(POLLING_INTERVAL)
                continue
            
            # Find new messages (after last_seen) - both user (from TUI) and assistant
            new_messages = []
            found_last_seen = last_seen is None
            
            for msg in messages:
                if msg["id"] == last_seen:
                    found_last_seen = True
                    continue
                
                # Include both user messages (from TUI) and assistant messages
                if found_last_seen and msg["role"] in ("user", "assistant"):
                    new_messages.append(msg)
            
            # Send new messages to Telegram
            for msg in new_messages:
                text = msg["text"]
                role = msg["role"]
                
                # Format differently based on role
                if role == "user":
                    notification = f"📝 Tú (TUI):\n{text}"
                else:
                    notification = f"🖥️ OpenCode:\n\n{text}"
                
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=truncate_response(notification),
                    )
                    logger.info("Sent polled message to chat %s: %s...", chat_id, text[:50])
                    
                    # Also send to notification group if configured
                    if NOTIFICATION_GROUP_ID != 0 and NOTIFICATION_GROUP_ID != chat_id:
                        try:
                            await app.bot.send_message(
                                chat_id=NOTIFICATION_GROUP_ID,
                                text=truncate_response(notification),
                            )
                        except Exception as notif_err:
                            logger.warning("Failed to send to notification group: %s", notif_err)
                            
                except Exception as send_err:
                    logger.warning("Failed to send polled message: %s", send_err)
            
            # Update last seen message ID to the latest message
            if messages:
                latest_msg = messages[-1]
                update_last_seen_message(latest_msg["id"])
                
        except Exception as exc:
            logger.exception("Polling error: %s", exc)
        
        await asyncio.sleep(POLLING_INTERVAL)


# ──────────────────────────────────────────────────────────────────────────────
# Post-init hook — launch background tasks after bot starts
# ──────────────────────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:  # type: ignore[type-arg]
    """Launch async background tasks once the Application is running."""
    asyncio.create_task(heartbeat(app))
    asyncio.create_task(poll_opencode_messages(app))
    logger.info("Background tasks launched (heartbeat, message polling)")


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    bootstrap()

    print(f"\n{'='*60}")
    print(f"  OpenCode Telegram Bridge (Multi-Port)")
    print(f"  Scanning ports: {OPENCODE_PORT_START}-{OPENCODE_PORT_END}")
    print(f"  Ready to connect to opencode sessions")
    print(f"{'='*60}\n")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("chatid", chatid_handler))
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("connect", connect_handler))
    app.add_handler(CommandHandler("exit", exit_handler))
    app.add_handler(CommandHandler("sessions", sessions_handler))
    app.add_handler(CallbackQueryHandler(connect_callback_handler, pattern="^connect:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, voice_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
