"""
Unit tests for bridge.py helpers.
Tests atomic writes, safe reads, session management, and response truncation.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import importlib
import sys


def load_bridge(tmp_path: Path):
    """Import (or reload) bridge with env vars pointing to tmp_path."""
    env_patch = {
        "BOT_TOKEN": "dummy:token",
        "ALLOWED_USER_IDS": "429591886",
    }
    with patch.dict(os.environ, env_patch):
        if "bridge" in sys.modules:
            del sys.modules["bridge"]
        import bridge as b
    return b


# ──────────────────────────────────────────────────────────────────────────────
# atomic_write / safe_read
# ──────────────────────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_writes_valid_json(self, tmp_path):
        b = load_bridge(tmp_path)
        target = tmp_path / "data.json"
        b.atomic_write(target, {"hello": "world"})
        assert json.loads(target.read_text()) == {"hello": "world"}

    def test_no_tmp_file_left_on_success(self, tmp_path):
        b = load_bridge(tmp_path)
        target = tmp_path / "data.json"
        b.atomic_write(target, {"x": 1})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_overwrites_existing_file(self, tmp_path):
        b = load_bridge(tmp_path)
        target = tmp_path / "data.json"
        b.atomic_write(target, {"v": 1})
        b.atomic_write(target, {"v": 2})
        assert json.loads(target.read_text()) == {"v": 2}


class TestSafeRead:
    def test_returns_default_when_file_missing(self, tmp_path):
        b = load_bridge(tmp_path)
        result = b.safe_read(tmp_path / "missing.json", {"default": True})
        assert result == {"default": True}

    def test_returns_default_on_malformed_json(self, tmp_path):
        b = load_bridge(tmp_path)
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        result = b.safe_read(bad, {"fallback": 42})
        assert result == {"fallback": 42}

    def test_reads_valid_json(self, tmp_path):
        b = load_bridge(tmp_path)
        good = tmp_path / "good.json"
        good.write_text('{"key": "val"}')
        assert b.safe_read(good, {}) == {"key": "val"}


# ──────────────────────────────────────────────────────────────────────────────
# Session management
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionManagement:
    def test_connect_session_stores_data(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        
        b.connect_session(chat_id=123, user_id=456, opencode_session_id="test-session-123")
        
        session = json.loads(b.SESSION_PATH.read_text())
        assert session["connected"] is True
        assert session["chat_id"] == 123
        assert session["user_id"] == 456
        assert session["opencode_session_id"] == "test-session-123"
        assert session["connected_at"] is not None

    def test_disconnect_session_clears_state(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.connect_session(chat_id=123, user_id=456, opencode_session_id="session-xyz")
        
        b.disconnect_session()
        
        session = json.loads(b.SESSION_PATH.read_text())
        assert session["connected"] is False
        assert session["chat_id"] is None
        assert session["opencode_session_id"] is None

    def test_get_opencode_session_id_returns_id_when_connected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.connect_session(chat_id=100, user_id=200, opencode_session_id="my-session")
        
        assert b.get_opencode_session_id() == "my-session"

    def test_get_opencode_session_id_returns_none_when_disconnected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        
        assert b.get_opencode_session_id() is None

    def test_get_active_chat_id_returns_id_when_connected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.connect_session(chat_id=777, user_id=888, opencode_session_id="sess")
        
        assert b.get_active_chat_id() == 777

    def test_get_active_chat_id_returns_none_when_disconnected(self, tmp_path):
        b = load_bridge(tmp_path)
        b.SESSION_PATH = tmp_path / "session.json"
        b.atomic_write(b.SESSION_PATH, dict(b.EMPTY_SESSION))
        
        assert b.get_active_chat_id() is None


# ──────────────────────────────────────────────────────────────────────────────
# Response truncation
# ──────────────────────────────────────────────────────────────────────────────

class TestTruncateResponse:
    def test_short_text_unchanged(self, tmp_path):
        b = load_bridge(tmp_path)
        text = "Hello world"
        assert b.truncate_response(text) == text

    def test_long_text_truncated(self, tmp_path):
        b = load_bridge(tmp_path)
        text = "x" * 5000
        result = b.truncate_response(text)
        assert len(result) <= b.MAX_MESSAGE_LEN
        assert "truncated" in result.lower()

    def test_exact_limit_unchanged(self, tmp_path):
        b = load_bridge(tmp_path)
        text = "y" * b.MAX_MESSAGE_LEN
        result = b.truncate_response(text)
        assert result == text


# ──────────────────────────────────────────────────────────────────────────────
# Allowed user IDs
# ──────────────────────────────────────────────────────────────────────────────

class TestAllowedUserIDs:
    def test_allowed_user_id_is_loaded(self, tmp_path):
        b = load_bridge(tmp_path)
        assert 429591886 in b.ALLOWED_USER_IDS

    def test_arbitrary_user_not_in_allowlist(self, tmp_path):
        b = load_bridge(tmp_path)
        assert 999999999 not in b.ALLOWED_USER_IDS
