"""One hostile message must not break the tools for the rest of the mailbox.

Any sender chooses the charsets, the header bytes and the MIME structure of what
they send. An unknown charset (or one whose codec refuses errors="replace") used to
raise out of the decoders, failing every list, search and read whose window held
the message. So did a malformed encoded-word, and a Date or Content-Disposition
header carrying raw 8-bit bytes; an attachment name in a codec that refuses
errors="replace" failed get, download and forward. A multipart nested thousands
deep raised RecursionError on read. Saved attachments also get the quarantine tag
macOS uses to make Gatekeeper check them.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

import server

HOSTILE_CHARSETS = ["x-bogus", "idna", "base64"]

ATTACHMENT_MESSAGE = (
    b"From: a@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="x"\r\n\r\n'
    b"--x\r\n"
    b"Content-Type: application/octet-stream\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b'Content-Disposition: attachment; filename="tool.command"\r\n\r\n'
    b"ZWNobyBoaQ==\r\n"
    b"--x--\r\n"
)


def _nested(depth: int) -> bytes:
    head = b"From: a@example.com\r\nSubject: nest\r\nMIME-Version: 1.0\r\n"
    body = b""
    for i in range(depth):
        body += f'Content-Type: multipart/mixed; boundary="b{i}"\r\n\r\n--b{i}\r\n'.encode()
    body += b"Content-Type: text/plain\r\n\r\nhi\r\n"
    for i in reversed(range(depth)):
        body += f"--b{i}--\r\n".encode()
    return head + body


class _Conn:
    """IMAP stand-in holding one message, UID 7, served as headers or in full."""

    def __init__(self, raw: bytes):
        self.raw = raw

    def select(self, mailbox, readonly=False):
        return ("OK", [b"1"])

    def uid(self, command, *args):
        if command == "SEARCH":
            return ("OK", [b"7"])
        raw = self.raw.split(b"\r\n\r\n", 1)[0] if "HEADER" in args[1] else self.raw
        return ("OK", [(b"7 (UID 7 FLAGS () RFC822 {%d}" % len(raw), raw), b")"])

    def logout(self):
        return ("BYE", [b""])


def _serve(monkeypatch, raw: bytes) -> None:
    monkeypatch.setattr(server, "_connect", lambda account=None: _Conn(raw))


def _download(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv(server.ALLOWED_DIRS_ENV, str(tmp_path))
    _serve(monkeypatch, ATTACHMENT_MESSAGE)
    return server.yahoo_download_attachments("7", out_dir=str(tmp_path / "dl"))[0]["saved_to"]


def _with_attachment_name(param: bytes) -> bytes:
    """ATTACHMENT_MESSAGE with its filename parameter replaced by param."""
    return ATTACHMENT_MESSAGE.replace(b'filename="tool.command"', param)


def _ready_to_forward(tmp_path, monkeypatch) -> list:
    """Config for forward, downloads allowed under tmp_path. Returns the saved drafts."""
    cfg = tmp_path / "accounts.json"
    cfg.write_text(
        json.dumps({"accounts": {"personal": {"email": "d@yahoo.com", "password": "PW"}}})
    )
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)
    monkeypatch.setenv(server.ALLOWED_DIRS_ENV, str(tmp_path))
    drafts: list = []

    def fake_save(folder, msg, flags="\\Seen", account=None):
        drafts.append(msg)
        return {"status": "ok", "folder": "Draft"}

    monkeypatch.setattr(server, "_save_to_folder", fake_save)
    return drafts


def _attachment_names(msg) -> list[str]:
    return [part.get_filename() for part in msg.walk() if part.get_filename()]


# ── Charsets ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("charset", HOSTILE_CHARSETS)
def test_a_header_in_a_hostile_charset_still_decodes(charset):
    assert server._decode_header(f"=?{charset}?Q?hello?=") == "hello"


@pytest.mark.parametrize("charset", HOSTILE_CHARSETS)
def test_a_body_in_a_hostile_charset_still_decodes(charset):
    raw = f"Subject: s\r\nContent-Type: text/plain; charset={charset}\r\n\r\nbody\r\n"

    assert server._get_text_body(server._parse_message(raw.encode())).strip() == "body"


@pytest.mark.parametrize("charset", HOSTILE_CHARSETS)
def test_list_and_search_survive_a_hostile_charset(monkeypatch, charset):
    raw = f"From: a@example.com\r\nSubject: =?{charset}?Q?hello?=\r\n\r\nbody\r\n".encode()
    _serve(monkeypatch, raw)

    assert [m["subject"] for m in server.yahoo_list_mail()] == ["hello"]
    assert server.yahoo_search_mail("χαίρε") == []  # the client-side, header-decoding path


@pytest.mark.parametrize("charset", HOSTILE_CHARSETS)
def test_an_attachment_name_in_a_hostile_charset_still_reads(tmp_path, monkeypatch, charset):
    # RFC 2231: idna made part.get_filename() raise UnicodeError.
    drafts = _ready_to_forward(tmp_path, monkeypatch)
    _serve(monkeypatch, _with_attachment_name(f"filename*={charset}''report.pdf".encode()))

    assert [a["filename"] for a in server.yahoo_get_mail("7")["attachments"]] == ["report.pdf"]
    saved = server.yahoo_download_attachments("7", out_dir=str(tmp_path / "dl"))
    assert Path(saved[0]["saved_to"]).name == "report.pdf"
    assert server.yahoo_forward_mail("7", "to@x.com")["forwarded_attachments"] == 1
    assert _attachment_names(drafts[0]) == ["report.pdf"]


# ── Encoded-words that will not decode ───────────────────────────────────

MALFORMED = "=?utf-8?b?a?="  # one base64 character: decode_header raises HeaderParseError


def test_a_malformed_encoded_word_comes_back_as_the_raw_header():
    assert server._decode_header(MALFORMED) == MALFORMED
    assert server._decode_header(f"Re: {MALFORMED}") == f"Re: {MALFORMED}"


def test_list_search_get_and_forward_survive_a_malformed_encoded_word(tmp_path, monkeypatch):
    _ready_to_forward(tmp_path, monkeypatch)
    raw = f"From: {MALFORMED} <a@example.com>\r\nSubject: {MALFORMED}\r\n\r\nx".encode()
    _serve(monkeypatch, raw)

    assert [m["subject"] for m in server.yahoo_list_mail()] == [MALFORMED]
    assert [m["subject"] for m in server.yahoo_search_mail("x")] == [MALFORMED]
    assert server.yahoo_search_mail("χαίρε") == []  # the client-side, header-decoding path
    assert server.yahoo_get_mail("7")["subject"] == MALFORMED
    assert server.yahoo_forward_mail("7", "to@x.com")["subject"] == f"Fwd: {MALFORMED}"


# ── Raw 8-bit header bytes ───────────────────────────────────────────────
#
# A header holding bytes that are not ASCII comes back from Message.get as an
# email.header.Header, not a str.


def test_a_date_with_raw_8bit_bytes_is_returned_as_text(monkeypatch):
    _serve(monkeypatch, b"Subject: s\r\nDate: Mon, 15 Sep 2026 09:00:00 +0300 \xe9\r\n\r\nx")

    for rows in (server.yahoo_list_mail(), server.yahoo_search_mail("s")):
        assert isinstance(rows[0]["date"], str)
        json.dumps(rows)  # a Header raised here, as it did in the MCP SDK's serialiser
    assert isinstance(server.yahoo_get_mail("7")["date"], str)


def test_a_top_level_content_disposition_with_raw_8bit_bytes_still_lists(monkeypatch):
    raw = b'Subject: s\r\nContent-Disposition: attachment; filename="\xe9.pdf"\r\n\r\nx'
    _serve(monkeypatch, raw)

    assert [m["has_attachments"] for m in server.yahoo_list_mail()] == [True]
    assert [a["filename"] for a in server.yahoo_get_mail("7")["attachments"]] == ["\ufffd.pdf"]


def test_an_attachment_header_with_raw_8bit_bytes_still_reads(tmp_path, monkeypatch):
    drafts = _ready_to_forward(tmp_path, monkeypatch)
    _serve(monkeypatch, _with_attachment_name(b'filename="caf\xe9.pdf"'))

    assert [a["filename"] for a in server.yahoo_get_mail("7")["attachments"]] == ["caf\ufffd.pdf"]
    saved = server.yahoo_download_attachments("7", out_dir=str(tmp_path / "dl"))
    assert Path(saved[0]["saved_to"]).read_bytes() == b"echo hi"
    assert server.yahoo_forward_mail("7", "to@x.com")["forwarded_attachments"] == 1
    assert _attachment_names(drafts[0]) == ["caf\ufffd.pdf"]


# ── MIME depth ───────────────────────────────────────────────────────────


def test_a_deeply_nested_message_reads_as_an_error_not_a_crash(tmp_path, monkeypatch):
    cfg = tmp_path / "accounts.json"
    cfg.write_text(
        json.dumps({"accounts": {"personal": {"email": "d@yahoo.com", "password": "PW"}}})
    )
    monkeypatch.setattr(server, "CONFIG_PATH", cfg)
    monkeypatch.setenv(server.ALLOWED_DIRS_ENV, str(tmp_path))
    _serve(monkeypatch, _nested(3000))

    assert "nested too deeply" in server.yahoo_get_mail("7")["error"]
    download = server.yahoo_download_attachments("7", out_dir=str(tmp_path / "dl"))
    assert "nested too deeply" in download[0]["error"]
    assert "nested too deeply" in server.yahoo_forward_mail("7", "to@x.com")["error"]


def test_ordinary_nesting_still_reads(monkeypatch):
    _serve(monkeypatch, _nested(50))

    assert server.yahoo_get_mail("7")["body"].strip() == "hi"


# ── Quarantine ───────────────────────────────────────────────────────────


def test_a_saved_attachment_is_tagged_for_quarantine(tmp_path, monkeypatch):
    calls = []
    fake_xattr = tmp_path / "xattr"
    fake_xattr.write_text("")
    monkeypatch.setattr(server, "XATTR_BIN", str(fake_xattr))
    monkeypatch.setattr(server.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    saved = _download(tmp_path, monkeypatch)

    assert len(calls) == 1
    xattr, flag, name, value, path = calls[0]
    assert (xattr, flag, name, path) == (str(fake_xattr), "-w", "com.apple.quarantine", saved)
    assert value.startswith("0081;") and value.endswith(";yahoo-access;")


def test_without_xattr_the_download_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "XATTR_BIN", str(tmp_path / "missing"))

    saved = _download(tmp_path, monkeypatch)

    assert Path(saved).read_bytes() == b"echo hi"


@pytest.mark.skipif(not os.path.exists("/usr/bin/xattr"), reason="macOS only")
def test_on_macos_the_quarantine_tag_lands_on_the_file(tmp_path, monkeypatch):
    saved = _download(tmp_path, monkeypatch)

    out = subprocess.run(
        ["/usr/bin/xattr", "-p", "com.apple.quarantine", saved], capture_output=True, text=True
    )
    assert out.stdout.startswith("0081;")
