"""
Integration tests for the opencode bridge.
Tests handlers with mocked Telegram and mocked opencode CLI execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def load_bridge(tmp_path: Path):
    """Import bridge with env vars and file paths redirected to tmp_path."""
    env_patch = {
        "BOT_TOKEN": "dummy:token",
        "ALLOWED_USER_IDS": "429591886",
    }
    with patch.dict(os.environ, env_patch):
        if "bridge" in sys.modules:
            del sys.modules["bridge"]
        import bridge as b

    # Redirect all file paths to tmp_path
    b.BRIDGE_DIR = tmp_path
    b.SESSION_PATH = tmp_path / "session.json"
    b.STATE_PATH = tmp_path / "state.json"
    b.UPLOADS_DIR = tmp_path / "uploads"
    return b


def make_update(
    user_id: int,
    chat_id: int,
    text: str = "",
) -> MagicMock:
    """Build a minimal mock telegram.Update."""
    user = SimpleNamespace(id=user_id, username=f"user_{user_id}")
    chat = SimpleNamespace(id=chat_id)
    chat.send_action = AsyncMock()
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    message.voice = None
    message.audio = None
    message.photo = []
    message.document = None
    message.caption = None

    update = MagicMock()
    update.effective_user = user
    update.effective_chat = chat
    update.message = message
    return update


def make_context(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# /start handler
# ──────────────────────────────────────────────────────────────────────────────


class TestStartHandler:
    def _bootstrap(self, b, tmp_path: Path):
        b.atomic_write(b.STATE_PATH, dict(b.EMPTY_STATE))
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

    @pytest.mark.asyncio
    async def test_start_lists_instances(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        instances = [
            {
                "port": 4096,
                "sessions": [
                    {
                        "id": "session-1234567890",
                        "directory": "/tmp/project-alpha",
                    }
                ],
            }
        ]

        with patch.object(b, "scan_opencode_ports", AsyncMock(return_value=instances)):
            await b.start_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Port 4096" in reply_text
        assert "project-alpha" in reply_text
        kwargs = update.message.reply_text.call_args[1]
        assert "reply_markup" in kwargs

    @pytest.mark.asyncio
    async def test_start_handles_no_instances(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        with patch.object(b, "scan_opencode_ports", AsyncMock(return_value=[])):
            await b.start_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "No hay instancias" in reply_text

    @pytest.mark.asyncio
    async def test_start_unauthorized_user_rejected(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=999999, chat_id=200)
        ctx = make_context()
        await b.start_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "denied" in reply_text.lower()


# ──────────────────────────────────────────────────────────────────────────────
# /connect handler
# ──────────────────────────────────────────────────────────────────────────────


class TestConnectHandler:
    def _bootstrap(self, b, tmp_path: Path):
        b.atomic_write(b.STATE_PATH, dict(b.EMPTY_STATE))
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

    @pytest.mark.asyncio
    async def test_connect_creates_session(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context(args=["my-opencode-session"])
        with patch.object(b, "find_session_port", AsyncMock(return_value=4096)), \
            patch.object(b, "fetch_session_messages", AsyncMock(return_value=[{"id": "msg-1"}])):
            await b.connect_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Connected" in reply_text
        assert "my-opencode-session" in reply_text

        session = json.loads(b.SESSION_PATH.read_text())
        assert session["connected"] is True
        assert session["opencode_session_id"] == "my-opencode-session"
        assert session["chat_id"] == 100
        assert session["user_id"] == 429591886

    @pytest.mark.asyncio
    async def test_connect_without_session_id_shows_usage(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context(args=[])
        await b.connect_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Usage" in reply_text
        assert "/sessions" in reply_text

    @pytest.mark.asyncio
    async def test_connect_unauthorized_rejected(self, tmp_path):
        b = load_bridge(tmp_path)
        self._bootstrap(b, tmp_path)

        update = make_update(user_id=999999, chat_id=200)
        ctx = make_context(args=["session-123"])
        await b.connect_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "denied" in reply_text.lower()

        session = json.loads(b.SESSION_PATH.read_text())
        assert session["connected"] is False


# ──────────────────────────────────────────────────────────────────────────────
# /exit handler
# ──────────────────────────────────────────────────────────────────────────────


class TestExitHandler:
    @pytest.mark.asyncio
    async def test_disconnect_clears_session(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        b.connect_session(chat_id=100, user_id=429591886, opencode_session_id="active-sess", port=4096)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()
        await b.exit_handler(update, ctx)

        session = json.loads(b.SESSION_PATH.read_text())
        assert session["connected"] is False
        assert session["opencode_session_id"] is None

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Disconnected" in reply_text
        assert "active-sess" in reply_text

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()
        await b.exit_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Not connected" in reply_text


# ──────────────────────────────────────────────────────────────────────────────
# /sessions handler
# ──────────────────────────────────────────────────────────────────────────────


class TestSessionsHandler:
    @pytest.mark.asyncio
    async def test_sessions_lists_available(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        fake_instances = [
            {
                "port": 4096,
                "sessions": [
                    {"id": "session-1", "directory": "/tmp/project-alpha", "title": "Primary"},
                    {"id": "session-2", "directory": "/tmp/project-alpha", "title": ""},
                ],
            }
        ]

        with patch.object(b, "scan_opencode_ports", AsyncMock(return_value=fake_instances)):
            await b.sessions_handler(update, ctx)

        # First call is "Fetching sessions..."
        # Second call is the actual list
        calls = update.message.reply_text.call_args_list
        assert len(calls) == 2
        assert "session-1" in calls[1][0][0]
        assert "session-2" in calls[1][0][0]

    @pytest.mark.asyncio
    async def test_sessions_handles_error(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        with patch.object(b, "scan_opencode_ports", AsyncMock(return_value=[])):
            await b.sessions_handler(update, ctx)

        calls = update.message.reply_text.call_args_list
        assert "No OpenCode instances" in calls[1][0][0]


# ──────────────────────────────────────────────────────────────────────────────
# Message handler (text → opencode run)
# ──────────────────────────────────────────────────────────────────────────────


class TestMessageHandler:
    def _connected_session(self, b, chat_id: int = 100, user_id: int = 429591886, session_id: str = "test-sess"):
        b.atomic_write(b.STATE_PATH, dict(b.EMPTY_STATE))
        b.connect_session(chat_id=chat_id, user_id=user_id, opencode_session_id=session_id, port=4096)

    @pytest.mark.asyncio
    async def test_message_calls_opencode_run(self, tmp_path):
        b = load_bridge(tmp_path)
        self._connected_session(b)

        update = make_update(user_id=429591886, chat_id=100, text="Hello Claude")
        ctx = make_context()

        with patch.object(b, "run_opencode", return_value=(True, "Hello! How can I help?")) as mock_run:
            await b.message_handler(update, ctx)
            mock_run.assert_awaited_once_with("test-sess", "Hello Claude", 4096)

        # Find the actual response (not the "Processing..." message)
        calls = update.message.reply_text.call_args_list
        response_text = calls[-1][0][0]
        assert "Hello! How can I help?" in response_text

    @pytest.mark.asyncio
    async def test_message_handles_opencode_error(self, tmp_path):
        b = load_bridge(tmp_path)
        self._connected_session(b)

        update = make_update(user_id=429591886, chat_id=100, text="Do something")
        ctx = make_context()

        with patch.object(b, "run_opencode", return_value=(False, "Session not found")):
            await b.message_handler(update, ctx)

        calls = update.message.reply_text.call_args_list
        response_text = calls[-1][0][0]
        assert "Error" in response_text
        assert "Session not found" in response_text

    @pytest.mark.asyncio
    async def test_message_truncates_long_response(self, tmp_path):
        b = load_bridge(tmp_path)
        self._connected_session(b)

        update = make_update(user_id=429591886, chat_id=100, text="Give me a long response")
        ctx = make_context()

        long_output = "x" * 5000
        with patch.object(b, "run_opencode", return_value=(True, long_output)):
            await b.message_handler(update, ctx)

        calls = update.message.reply_text.call_args_list
        response_text = calls[-1][0][0]
        assert len(response_text) <= b.MAX_MESSAGE_LEN
        assert "truncated" in response_text.lower()

    @pytest.mark.asyncio
    async def test_message_unauthorized_rejected(self, tmp_path):
        b = load_bridge(tmp_path)
        self._connected_session(b)

        update = make_update(user_id=8888, chat_id=100, text="Hack attempt")
        ctx = make_context()

        with patch.object(b, "run_opencode") as mock_run:
            await b.message_handler(update, ctx)
            mock_run.assert_not_awaited()

        reply_text = update.message.reply_text.call_args[0][0]
        assert "denied" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_message_without_session_warns_user(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

        update = make_update(user_id=429591886, chat_id=100, text="Hello?")
        ctx = make_context()

        with patch.object(b, "run_opencode") as mock_run:
            await b.message_handler(update, ctx)
            mock_run.assert_not_awaited()

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Not connected" in reply_text


class TestVoiceHandler:
    @pytest.mark.asyncio
    async def test_voice_unauthorized_rejected(self, tmp_path):
        b = load_bridge(tmp_path)
        update = make_update(user_id=111, chat_id=100)
        update.message.voice = MagicMock()
        ctx = make_context()
        await b.voice_handler(update, ctx)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "denied" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_voice_transcribes_and_executes(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        b.connect_session(chat_id=100, user_id=429591886, opencode_session_id="sess", port=4096)

        update = make_update(user_id=429591886, chat_id=100)

        file_obj = SimpleNamespace()

        async def fake_download(*, custom_path):
            Path(custom_path).write_bytes(b"voice")

        file_obj.download_to_drive = AsyncMock(side_effect=fake_download)

        voice = SimpleNamespace()
        voice.get_file = AsyncMock(return_value=file_obj)
        update.message.voice = voice

        ctx = make_context()

        with patch.object(b, "transcribe_audio_file", AsyncMock(return_value="haz algo")) as mock_transcribe, \
            patch.object(b, "execute_user_prompt", AsyncMock()) as mock_exec:
            await b.voice_handler(update, ctx)

        mock_transcribe.assert_awaited()
        mock_exec.assert_awaited_once_with(update, ctx, "haz algo")
        assert update.message.reply_text.call_count == 0


class TestPhotoHandler:
    def _connect(self, b, chat_id: int = 100):
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        b.atomic_write(b.STATE_PATH, dict(b.EMPTY_STATE))
        b.connect_session(chat_id=chat_id, user_id=429591886, opencode_session_id="sess-photo", port=4096)

    @pytest.mark.asyncio
    async def test_photo_handler_saves_file_and_notifies(self, tmp_path):
        b = load_bridge(tmp_path)
        self._connect(b)

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        async def fake_download(*, custom_path):
            Path(custom_path).write_bytes(b"imgdata")

        telegram_file = SimpleNamespace(
            file_path="/tmp/photo.jpg",
            download_to_drive=AsyncMock(side_effect=fake_download),
        )

        photo = SimpleNamespace(
            file_id="photo-1",
            file_unique_id="unique-photo",
            width=128,
            height=64,
        )
        photo.get_file = AsyncMock(return_value=telegram_file)

        update.message.photo = [photo]
        update.message.caption = "un dibujo"

        with patch.object(b, "execute_user_prompt", AsyncMock()) as mock_exec:
            await b.photo_handler(update, ctx)

        saved_files = list(b.UPLOADS_DIR.glob("*.jpg"))
        assert len(saved_files) == 1
        assert saved_files[0].read_bytes() == b"imgdata"

        assert mock_exec.await_count == 1
        sent_text = mock_exec.await_args_list[0].args[2]
        assert "Saved path" in sent_text
        assert "Resolution" in sent_text
        assert "un dibujo" in sent_text

    @pytest.mark.asyncio
    async def test_photo_handler_rejects_when_not_connected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))

        update = make_update(user_id=429591886, chat_id=100)
        ctx = make_context()

        telegram_file = SimpleNamespace(
            file_path="/tmp/p.png",
            download_to_drive=AsyncMock(),
        )

        photo = SimpleNamespace(file_id="p", file_unique_id="p", width=1, height=1)
        photo.get_file = AsyncMock(return_value=telegram_file)
        update.message.photo = [photo]

        with patch.object(b, "execute_user_prompt", AsyncMock()) as mock_exec:
            await b.photo_handler(update, ctx)

        mock_exec.assert_not_called()
        update.message.reply_text.assert_awaited()

# ──────────────────────────────────────────────────────────────────────────────
# OpenCode execution (mocked subprocess)
# ──────────────────────────────────────────────────────────────────────────────


class TestRunOpencode:
    @pytest.mark.asyncio
    async def test_run_opencode_success(self, tmp_path):
        b = load_bridge(tmp_path)

        # Mock successful subprocess execution
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"Response from opencode", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            success, output = await b.run_opencode("session-123", "Hello", 4096)

        assert success is True
        assert output == "Response from opencode"
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "opencode" in call_args
        assert "run" in call_args
        assert "-s" in call_args
        assert "session-123" in call_args
        assert "Hello" in call_args

    @pytest.mark.asyncio
    async def test_run_opencode_failure(self, tmp_path):
        b = load_bridge(tmp_path)

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error: session not found"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            success, output = await b.run_opencode("bad-session", "Hello", 4096)

        assert success is False
        assert "session not found" in output

    @pytest.mark.asyncio
    async def test_run_opencode_timeout(self, tmp_path):
        b = load_bridge(tmp_path)

        mock_process = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            success, output = await b.run_opencode("session-123", "Long running task", 4096)

        assert success is False
        assert "timed out" in output.lower()
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_opencode_command_not_found(self, tmp_path):
        b = load_bridge(tmp_path)

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            success, output = await b.run_opencode("session-123", "Hello", 4096)

        assert success is False
        assert "not found" in output.lower()


class TestListOpencodeSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_success(self, tmp_path):
        b = load_bridge(tmp_path)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"session-1\nsession-2\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            success, output = await b.list_opencode_sessions()

        assert success is True
        assert "session-1" in output
        assert "session-2" in output
        call_args = mock_exec.call_args[0]
        assert "opencode" in call_args
        assert "session" in call_args
        assert "list" in call_args

    @pytest.mark.asyncio
    async def test_list_sessions_failure(self, tmp_path):
        b = load_bridge(tmp_path)

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            success, output = await b.list_opencode_sessions()

        assert success is False
