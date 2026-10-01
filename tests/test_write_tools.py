import json

import server


def _cfg(tmp_path, monkeypatch):
    cfg = tmp_path / "accounts.json"
    cfg.write_text(
        json.dumps(
            {
                "accounts": {"personal": {"email": "d@yahoo.com", "password": "PW"}},
                "default": "personal",
            }
        )
    )
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)


def test_send_mail_draft_first_appends_not_sends(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    calls = {}

    def fake_save(folder, msg, flags="\\Seen", account=None):
        calls["folder"] = folder
        calls["flags"] = flags
        return {"status": "ok", "folder": "Draft"}

    monkeypatch.setattr(server, "_save_to_folder", fake_save)

    def boom(*a, **k):
        raise AssertionError("SMTP must not be used for a draft")

    monkeypatch.setattr(server, "_smtp_connect", boom)

    res = server.yahoo_send_mail("to@x.com", "Hi", "Body")  # send_now defaults False
    assert res["status"] == "draft_saved"
    assert calls["folder"] == "__DRAFTS__"


def test_send_mail_send_now_dispatches(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)

    class _SMTP:
        def sendmail(self, frm, rcpts, body):
            _SMTP.sent = (frm, tuple(rcpts))

        def quit(self):
            pass

    monkeypatch.setattr(server, "_smtp_connect", lambda account=None: _SMTP())
    monkeypatch.setattr(
        server, "_save_to_folder", lambda *a, **k: {"status": "ok", "folder": "Sent"}
    )
    res = server.yahoo_send_mail("to@x.com", "Hi", "Body", send_now=True)
    assert res["status"] == "sent"
    assert _SMTP.sent[1] == ("to@x.com",)
