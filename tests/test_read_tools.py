import json

import server


class _FakeConn:
    """Minimal IMAP stand-in for list_folders."""

    def list(self):
        return ("OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Sent"'])

    def logout(self):
        return ("BYE", [b""])


def test_list_folders_parses_names(tmp_path, monkeypatch):
    cfg = tmp_path / "accounts.json"
    cfg.write_text(
        json.dumps({"accounts": {"personal": {"email": "d@yahoo.com"}}, "default": "personal"})
    )
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)
    monkeypatch.setattr(server, "_connect", lambda account=None: _FakeConn())
    folders = server.yahoo_list_folders()
    assert "INBOX" in folders and "Sent" in folders
