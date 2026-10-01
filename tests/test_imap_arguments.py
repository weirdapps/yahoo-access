"""Caller-supplied IMAP arguments cannot smuggle in a second command.

CR, LF or NUL inside a command line ends it there, and Python 3.12's imaplib sends
them as given, so a msg_id, folder or search query carrying one could run, say,
UID STORE 1:* +FLAGS (\\Deleted) through a read-only tool. Such arguments are now
refused, msg_id must be a single UID everywhere, and search text goes out as an
IMAP quoted string.
"""

import pytest

import server

INJECTED = "7\r\nZ1 UID STORE 1:* +FLAGS (\\Deleted)"
BAD_IDS = [INJECTED, "1:*", "3,4", "abc", ""]


class _RecordingConn:
    """IMAP stand-in that records every command and finds nothing."""

    def __init__(self):
        self.calls = []

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox))
        return ("OK", [b"0"])

    def uid(self, command, *args):
        self.calls.append((command, *args))
        return ("OK", [b""])

    def logout(self):
        return ("BYE", [b""])


def _no_imap(monkeypatch) -> None:
    def boom(account=None):
        raise AssertionError("a refused argument must be refused before IMAP is touched")

    monkeypatch.setattr(server, "_connect", boom)


def _error(result) -> str:
    return result[0]["error"] if isinstance(result, list) else result["error"]


@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda msg_id: server.yahoo_get_mail(msg_id), id="get"),
        pytest.param(lambda msg_id: server.yahoo_download_attachments(msg_id), id="download"),
        pytest.param(lambda msg_id: server.yahoo_forward_mail(msg_id, "to@x.com"), id="forward"),
    ],
)
def test_read_and_forward_refuse_a_msg_id_that_is_not_one_uid(monkeypatch, call, bad):
    _no_imap(monkeypatch)

    assert "msg_id must be one message UID" in _error(call(bad))


@pytest.mark.parametrize("name", ["INBOX\r\nZ1 SELECT Trash", "a\nb", "a\rb", "a\0b"])
def test_folder_names_with_line_breaks_are_refused(name):
    with pytest.raises(ValueError, match="CR, LF or NUL"):
        server._q(name)


def test_a_tool_sends_nothing_for_a_folder_with_a_line_break(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "_connect", lambda account=None: conn)

    with pytest.raises(ValueError, match="CR, LF or NUL"):
        server.yahoo_list_mail(folder="INBOX\r\nZ1 SELECT Trash")

    assert conn.calls == []


@pytest.mark.parametrize("query", [INJECTED, "a\nb", "a\rb", "a\0b", "πληρωμή\r\nZ1 NOOP"])
def test_search_refuses_line_breaks_before_connecting(monkeypatch, query):
    _no_imap(monkeypatch)

    with pytest.raises(ValueError, match="CR, LF or NUL"):
        server.yahoo_search_mail(query)


@pytest.mark.parametrize(
    ("field", "criteria"),
    [
        ("subject", '(SUBJECT "say \\"hi\\" \\\\ bye")'),
        ("from", '(FROM "say \\"hi\\" \\\\ bye")'),
        ("body", '(BODY "say \\"hi\\" \\\\ bye")'),
        (
            "all",
            '(OR OR SUBJECT "say \\"hi\\" \\\\ bye" FROM "say \\"hi\\" \\\\ bye" '
            'BODY "say \\"hi\\" \\\\ bye")',
        ),
    ],
)
def test_search_sends_the_query_as_an_imap_quoted_string(monkeypatch, field, criteria):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "_connect", lambda account=None: conn)

    server.yahoo_search_mail('say "hi" \\ bye', field=field)

    assert ("SEARCH", None, criteria) in conn.calls
