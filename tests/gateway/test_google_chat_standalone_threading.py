"""Standalone Google Chat threading contract.

The REST sender must explicitly opt into replies with ``messageReplyOption``:
Google's default silently starts a new thread and ignores both ``thread.name``
and ``threadKey``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys

import plugins.platforms.google_chat.adapter as adapter_module


@pytest.fixture
def sender(monkeypatch):
    """Force SA success and isolate the aiohttp transport, returning the mock session."""
    creds = MagicMock()
    creds.refresh = MagicMock()
    creds.token = "test-token"
    monkeypatch.setattr(adapter_module, "_load_sa_credentials_from", MagicMock(return_value=creds))
    session = MagicMock()
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={
        "name": "spaces/S/messages/M",
        "thread": {"name": "spaces/S/threads/T", "threadKey": "daily-key"},
    })
    response.text = AsyncMock(return_value="ok")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.post = MagicMock(return_value=response)
    mocked_http = SimpleNamespace(
        ClientSession=MagicMock(return_value=session), ClientTimeout=MagicMock())
    monkeypatch.setitem(sys.modules, "aiohttp", mocked_http)
    monkeypatch.setattr(adapter_module, "service_account", object())
    monkeypatch.setattr(adapter_module, "_GoogleAuthRequest", MagicMock())
    return session


def _post_call(session):
    assert session.post.call_count == 1
    args, kwargs = session.post.call_args
    return args[0], kwargs


@pytest.mark.asyncio
async def test_thread_key_sends_reply_option_and_thread_key(sender):
    result = await adapter_module._standalone_send(
        SimpleNamespace(extra={}), "spaces/S", "hello", thread_key="daily-key")

    print("RESULT", result)
    url, kwargs = _post_call(sender)
    assert url == "https://chat.googleapis.com/v1/spaces/S/messages"
    assert kwargs["params"] == {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
    assert kwargs["json"]["thread"] == {"threadKey": "daily-key"}
    assert "name" not in kwargs["json"]["thread"]
    assert result["success"] is True
    assert result["thread_id"] == "spaces/S/threads/T"
    assert result["thread_key_used"] == "daily-key"


@pytest.mark.asyncio
async def test_thread_id_sends_reply_option_and_thread_name(sender):
    result = await adapter_module._standalone_send(
        SimpleNamespace(extra={}), "spaces/S", "hello",
        thread_id="spaces/S/threads/T")

    url, kwargs = _post_call(sender)
    assert kwargs["params"] == {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
    assert kwargs["json"]["thread"] == {"name": "spaces/S/threads/T"}
    assert "threadKey" not in kwargs["json"]["thread"]
    assert result["success"] is True
    assert result["thread_id"] == "spaces/S/threads/T"
    assert "thread_key_used" not in result


@pytest.mark.asyncio
async def test_both_thread_id_and_key_are_rejected(sender):
    result = await adapter_module._standalone_send(
        SimpleNamespace(extra={}), "spaces/S", "hello",
        thread_id="spaces/S/threads/T", thread_key="daily-key")
    assert "mutually exclusive" in result["error"]
    sender.post.assert_not_called()


def test_thread_key_charset_is_conservative():
    assert adapter_module._THREAD_KEY_RE.fullmatch("kvk-zabbix_2026-10-12")
    assert not adapter_module._THREAD_KEY_RE.fullmatch("bad key")
    assert not adapter_module._THREAD_KEY_RE.fullmatch("")
    assert not adapter_module._THREAD_KEY_RE.fullmatch("k" * 65)
