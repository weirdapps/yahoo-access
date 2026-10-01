import json

import pytest

import server


def _write_config(tmp_path, monkeypatch, data):
    cfg = tmp_path / "accounts.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)
    return cfg


def test_keychain_first(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "accounts": {
                "personal": {"email": "d@yahoo.com", "keychain_service": "yahoo-mail-personal"}
            },
            "default": "personal",
        },
    )
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: "KEYCHAIN_PW")
    monkeypatch.setenv("YAHOO_APP_PASSWORD_PERSONAL", "ENV_PW")
    assert server._load_credentials() == ("d@yahoo.com", "KEYCHAIN_PW")


def test_env_fallback_when_no_keychain(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "accounts": {"work": {"email": "w@yahoo.com", "keychain_service": "yahoo-mail-work"}},
            "default": "work",
        },
    )
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: None)
    monkeypatch.setenv("YAHOO_APP_PASSWORD_WORK", "ENV_PW")
    assert server._load_credentials("work") == ("w@yahoo.com", "ENV_PW")


def test_inline_last_resort(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "accounts": {"work": {"email": "w@yahoo.com", "password": "INLINE_PW"}},
            "default": "work",
        },
    )
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: None)
    monkeypatch.delenv("YAHOO_APP_PASSWORD_WORK", raising=False)
    assert server._load_credentials("work") == ("w@yahoo.com", "INLINE_PW")


def test_missing_password_raises_with_fix_hint(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "accounts": {"work": {"email": "w@yahoo.com", "keychain_service": "yahoo-mail-work"}},
            "default": "work",
        },
    )
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: None)
    monkeypatch.delenv("YAHOO_APP_PASSWORD_WORK", raising=False)
    with pytest.raises(ValueError, match="add-generic-password"):
        server._load_credentials("work")


def test_unknown_account_raises(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        {
            "accounts": {"personal": {"email": "d@yahoo.com"}},
            "default": "personal",
        },
    )
    with pytest.raises(ValueError, match="not found"):
        server._load_credentials("nobody")
