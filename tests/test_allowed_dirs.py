"""Local file paths must sit inside an allowed folder.

Mail content steers the agent that calls these tools, so without a fence a crafted
message could have yahoo_download_attachments write a file anywhere the user can,
or have yahoo_send_mail attach any readable file. The default list is ~/Downloads
plus the temp folders, so the folders that hold the user's own documents are an
opt-in. YAHOO_MAIL_ALLOWED_DIRS (paths separated by os.pathsep) replaces the
default list, and symlinks are followed before the check.
"""

import json
import os
import tempfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

import server


@pytest.fixture
def allowed(tmp_path, monkeypatch):
    """The one allowed folder. Everything else under tmp_path is outside the fence."""
    folder = tmp_path / "allowed"
    folder.mkdir()
    monkeypatch.setenv(server.ALLOWED_DIRS_ENV, str(folder))
    return folder


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


def _message_with_attachment(filename: str) -> bytes:
    msg = MIMEMultipart()
    msg.attach(MIMEText("body"))
    part = MIMEApplication(b"PAYLOAD")
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)
    return msg.as_bytes()


class _Conn:
    """IMAP stand-in holding one message, UID 7."""

    def __init__(self, raw: bytes):
        self.raw = raw

    def select(self, mailbox, readonly=False):
        return ("OK", [b"1"])

    def uid(self, command, *args):
        return ("OK", [(b"1 (UID 7 RFC822 {%d}" % len(self.raw), self.raw), b")"])

    def logout(self):
        return ("BYE", [b""])


def _serve(monkeypatch, filename: str) -> None:
    raw = _message_with_attachment(filename)
    monkeypatch.setattr(server, "_connect", lambda account=None: _Conn(raw))


def _no_imap(monkeypatch) -> None:
    def boom(account=None):
        raise AssertionError("a refused path must be refused before IMAP is touched")

    monkeypatch.setattr(server, "_connect", boom)


def _no_save_or_send(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("nothing may be saved or sent")

    monkeypatch.setattr(server, "_save_to_folder", boom)
    monkeypatch.setattr(server, "_smtp_connect", boom)


def _capture_draft(monkeypatch) -> dict:
    saved: dict = {}

    def fake_save(folder, msg, flags="\\Seen", account=None):
        saved["msg"] = msg
        return {"status": "ok", "folder": "Draft"}

    monkeypatch.setattr(server, "_save_to_folder", fake_save)
    return saved


def _attachment_names(msg) -> list[str]:
    return [part.get_filename() for part in msg.walk() if part.get_filename()]


# ── The list itself ──────────────────────────────────────────────────────


def test_the_default_list_is_the_documented_folders(monkeypatch):
    monkeypatch.delenv(server.ALLOWED_DIRS_ENV, raising=False)
    documented = [Path.home() / "Downloads", Path(tempfile.gettempdir()), Path("/tmp")]

    assert server._allowed_dirs() == [p.resolve() for p in documented]


# Where users keep their own documents. None is allowed until the user names it.
USER_FOLDERS = ["Desktop", "Documents", "Pictures", "Library/CloudStorage"]

# With HOME inside a temp folder (some sandboxes do that), the default list does
# reach these folders, so there is nothing to test.
home_outside_temp = pytest.mark.skipif(
    any(
        Path.home().resolve().is_relative_to(Path(t).resolve())
        for t in (tempfile.gettempdir(), "/tmp")
    ),
    reason="HOME is inside a temp folder, which the default list allows",
)


@home_outside_temp
@pytest.mark.parametrize("folder", USER_FOLDERS)
def test_by_default_no_file_from_your_own_folders_can_be_sent(tmp_path, monkeypatch, folder):
    # The exfiltration half of the fence: a crafted message that steers the agent
    # into send_now=True with a local attachment gets nothing out of these folders.
    monkeypatch.delenv(server.ALLOWED_DIRS_ENV, raising=False)
    _cfg(tmp_path, monkeypatch)
    _no_save_or_send(monkeypatch)
    secret = Path.home() / folder / "tax-return.pdf"

    res = server.yahoo_send_mail("to@x.com", "S", "B", attachments=[str(secret)], send_now=True)

    assert server.ALLOWED_DIRS_ENV in res["error"]


@home_outside_temp
@pytest.mark.parametrize("folder", USER_FOLDERS)
def test_by_default_nothing_is_downloaded_into_your_own_folders(monkeypatch, folder):
    monkeypatch.delenv(server.ALLOWED_DIRS_ENV, raising=False)
    _no_imap(monkeypatch)

    res = server.yahoo_download_attachments("7", out_dir=str(Path.home() / folder))

    assert server.ALLOWED_DIRS_ENV in res[0]["error"]


def test_the_env_var_replaces_the_default_list(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv(server.ALLOWED_DIRS_ENV, os.pathsep.join([str(a), str(b)]))

    assert server._allowed_dirs() == [a.resolve(), b.resolve()]
    with pytest.raises(PermissionError):
        server._allowed_path(Path.home() / "Downloads" / "x.pdf", "Attachment")


def test_the_default_download_folder_is_inside_the_default_list(monkeypatch):
    monkeypatch.delenv(server.ALLOWED_DIRS_ENV, raising=False)

    resolved = server._allowed_path(server.DEFAULT_DOWNLOAD_DIR, "Download folder")

    assert resolved == server.DEFAULT_DOWNLOAD_DIR.resolve()


def test_a_refusal_names_the_env_var(allowed, tmp_path):
    with pytest.raises(PermissionError, match=server.ALLOWED_DIRS_ENV):
        server._allowed_path(tmp_path / "elsewhere", "Attachment")


# ── Downloads ────────────────────────────────────────────────────────────


def test_download_into_an_allowed_folder_saves_the_file(allowed, monkeypatch):
    _serve(monkeypatch, "report.pdf")
    out = allowed / "mail"

    res = server.yahoo_download_attachments("7", out_dir=str(out))

    assert res[0]["saved_to"] == str(out.resolve() / "report.pdf")
    assert (out / "report.pdf").read_bytes() == b"PAYLOAD"


def test_download_without_out_dir_still_uses_the_default_folder(allowed, monkeypatch):
    default = allowed / "Downloads"
    monkeypatch.setattr(server, "DEFAULT_DOWNLOAD_DIR", default)
    _serve(monkeypatch, "report.pdf")

    server.yahoo_download_attachments("7")

    assert (default / "report.pdf").read_bytes() == b"PAYLOAD"


@pytest.mark.parametrize("where", ["elsewhere", "allowed/../elsewhere"])
def test_download_outside_the_allowed_folders_is_refused(allowed, tmp_path, monkeypatch, where):
    _no_imap(monkeypatch)

    res = server.yahoo_download_attachments("7", out_dir=str(tmp_path / where))

    assert server.ALLOWED_DIRS_ENV in res[0]["error"]
    assert not (tmp_path / "elsewhere").exists()


def test_download_through_a_symlink_leading_out_is_refused(allowed, tmp_path, monkeypatch):
    _no_imap(monkeypatch)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)

    res = server.yahoo_download_attachments("7", out_dir=str(allowed / "link"))

    assert server.ALLOWED_DIRS_ENV in res[0]["error"]
    assert list(outside.iterdir()) == []


def test_a_dotfile_attachment_is_saved_under_a_visible_name(allowed, monkeypatch):
    _serve(monkeypatch, ".zshenv")

    res = server.yahoo_download_attachments("7", out_dir=str(allowed))

    assert Path(res[0]["saved_to"]).name == "_zshenv"
    assert not (allowed / ".zshenv").exists()


# ── Attachments on outgoing mail ─────────────────────────────────────────


def test_send_attaches_a_file_from_an_allowed_folder(allowed, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    saved = _capture_draft(monkeypatch)
    report = allowed / "report.pdf"
    report.write_bytes(b"%PDF")

    res = server.yahoo_send_mail("to@x.com", "S", "B", attachments=[str(report)])

    assert res["status"] == "draft_saved"
    assert _attachment_names(saved["msg"]) == ["report.pdf"]


def test_a_symlink_between_allowed_files_keeps_the_given_name(allowed, tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    saved = _capture_draft(monkeypatch)
    (allowed / "report-v3-final.pdf").write_bytes(b"%PDF")
    (allowed / "report.pdf").symlink_to(allowed / "report-v3-final.pdf")

    server.yahoo_send_mail("to@x.com", "S", "B", attachments=[str(allowed / "report.pdf")])

    assert _attachment_names(saved["msg"]) == ["report.pdf"]


@pytest.mark.parametrize("send_now", [False, True])
def test_send_refuses_an_attachment_outside_the_allowed_folders(
    allowed, tmp_path, monkeypatch, send_now
):
    _cfg(tmp_path, monkeypatch)
    _no_save_or_send(monkeypatch)
    key = tmp_path / "id_ed25519"
    key.write_text("PRIVATE KEY")
    report = allowed / "report.pdf"
    report.write_bytes(b"%PDF")

    # The refused file is not dropped so the rest can go: the whole call fails.
    res = server.yahoo_send_mail(
        "to@x.com", "S", "B", attachments=[str(report), str(key)], send_now=send_now
    )

    assert server.ALLOWED_DIRS_ENV in res["error"]


def test_send_refuses_a_symlink_that_leads_out_of_the_allowed_folders(
    allowed, tmp_path, monkeypatch
):
    _cfg(tmp_path, monkeypatch)
    _no_save_or_send(monkeypatch)
    key = tmp_path / "id_ed25519"
    key.write_text("PRIVATE KEY")
    (allowed / "invoice.pdf").symlink_to(key)

    res = server.yahoo_send_mail("to@x.com", "S", "B", attachments=[str(allowed / "invoice.pdf")])

    assert server.ALLOWED_DIRS_ENV in res["error"]
