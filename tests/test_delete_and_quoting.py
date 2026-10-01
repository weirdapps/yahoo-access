import re

import server


class FakeConn:
    """Records IMAP calls; returns canned responses."""

    def __init__(self, exists=0, list_lines=None):
        self.exists = exists
        self._list = list_lines or [b'(\\Trash \\HasNoChildren) "/" "Trash"']
        self.calls = []

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return ("OK", [str(self.exists).encode()])

    def search(self, charset, *criteria):
        self.calls.append(("search", criteria))
        return ("OK", [b""])

    def store(self, seq, flag, value):
        self.calls.append(("store", seq, flag, value))
        return ("OK", [b""])

    def expunge(self):
        self.calls.append(("expunge",))
        return ("OK", [b""])

    def copy(self, seq, dest):
        self.calls.append(("copy", seq, dest))
        return ("OK", [b""])

    def capability(self):
        # Neither MOVE nor UIDPLUS, so moves and deletes take the fallback path.
        return ("OK", [b"IMAP4rev1"])

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            # "UID <n>" is the existence check a move/delete makes first: answer
            # it with that UID. Any other search finds nothing.
            only = re.search(r"UID (\d+)", " ".join(a for a in args if a))
            return ("OK", [only.group(1).encode() if only else b""])
        return ("OK", [b""])

    def list(self):
        return ("OK", self._list)

    def logout(self):
        return ("BYE", [b""])


def test_q_quotes_only_when_needed():
    assert server._q("INBOX") == "INBOX"
    assert server._q("Bulk Mail") == '"Bulk Mail"'
    assert server._q('a"b') == '"a\\"b"'
    assert server._q("a\\b") == '"a\\\\b"'


def test_read_tool_quotes_space_folder(monkeypatch):
    fc = FakeConn()
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    server.yahoo_list_mail(folder="Bulk Mail")
    assert ("select", '"Bulk Mail"', True) in fc.calls


def test_empty_folder_dry_run_does_not_delete(monkeypatch):
    fc = FakeConn(exists=5)
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    res = server.yahoo_empty_folder("Bulk")
    assert res["status"] == "dry_run"
    assert res["would_delete"] == 5
    assert not any(c[0] in ("store", "expunge") for c in fc.calls)


def test_empty_folder_confirm_purges(monkeypatch):
    fc = FakeConn(exists=5)
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    res = server.yahoo_empty_folder("Bulk Mail", confirm=True)
    assert res["status"] == "emptied"
    assert res["deleted"] == 5
    assert ("select", '"Bulk Mail"', False) in fc.calls  # write mode + quoted
    assert any(c[0] == "store" for c in fc.calls)
    assert ("expunge",) in fc.calls


def test_empty_folder_confirm_already_empty(monkeypatch):
    fc = FakeConn(exists=0)
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    res = server.yahoo_empty_folder("Trash", confirm=True)
    assert res["status"] == "already_empty"
    assert not any(c[0] == "expunge" for c in fc.calls)


def test_delete_mail_permanent(monkeypatch):
    fc = FakeConn(exists=3)
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    res = server.yahoo_delete_mail("2", folder="INBOX", permanent=True)
    assert res["status"] == "deleted_permanent"
    assert ("uid", "STORE", "2", "+FLAGS", "(\\Deleted)") in fc.calls
    assert ("expunge",) in fc.calls  # no UIDPLUS advertised: the bare-EXPUNGE fallback
    assert not any(c[:2] == ("uid", "COPY") for c in fc.calls)  # no move on permanent


def test_delete_mail_soft_moves_to_trash(monkeypatch):
    fc = FakeConn(exists=3)
    monkeypatch.setattr(server, "_connect", lambda account=None: fc)
    res = server.yahoo_delete_mail("2", folder="INBOX")
    assert res["status"] == "moved_to_trash"
    assert res["trash"] == "Trash"
    assert ("uid", "COPY", "2", "Trash") in fc.calls
    assert ("expunge",) in fc.calls
