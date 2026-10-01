import imaplib
import json

import server


def _cfg(tmp_path, monkeypatch):
    cfg = tmp_path / "accounts.json"
    cfg.write_text(
        json.dumps(
            {
                "accounts": {"personal": {"email": "d@yahoo.com", "keychain_service": "s"}},
                "default": "personal",
            }
        )
    )
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: "PW")


class _FakeIMAP:
    """Minimal IMAP stand-in whose login succeeds."""

    def __init__(self, *a, **k):
        pass

    def login(self, u, p):
        return ("OK", [b""])

    def logout(self):
        return ("BYE", [b""])


def test_check_auth_ok(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAP)
    res = server.yahoo_check_auth()
    assert res["personal"]["ok"] is True


def test_check_auth_login_failure_has_imap_hint(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)

    class _BadIMAP(_FakeIMAP):
        def login(self, u, p):
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _BadIMAP)
    res = server.yahoo_check_auth("personal")
    assert res["personal"]["ok"] is False
    assert "IMAP" in res["personal"]["hint"]


def test_check_auth_missing_credentials(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_keychain_password", lambda svc, email: None)
    monkeypatch.delenv("YAHOO_APP_PASSWORD_PERSONAL", raising=False)
    res = server.yahoo_check_auth("personal")
    assert res["personal"]["ok"] is False
    assert res["personal"]["stage"] == "credentials"
