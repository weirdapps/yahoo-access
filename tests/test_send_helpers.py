import server


def test_collect_recipients_dedupes_preserving_order():
    out = server._collect_recipients("a@x.com, b@x.com", cc="a@x.com", bcc="c@x.com")
    assert out == ["a@x.com", "b@x.com", "c@x.com"]


def test_build_message_uses_yahoo_message_id_domain():
    msg = server._build_message("d@yahoo.com", "to@x.com", "Subj", "Body")
    assert msg["Message-ID"].endswith("@yahoo.com>")
    assert msg["To"] == "to@x.com"
    assert msg["Subject"] == "Subj"


def test_build_message_html_flag():
    msg = server._build_message("d@yahoo.com", "to@x.com", "S", "<b>hi</b>", html=True)
    payload = msg.as_string()
    assert "text/html" in payload


def test_find_special_folder_prefers_yahoo_draft():
    class _C:
        def list(self):
            return ("OK", [b'(\\HasNoChildren) "/" "Draft"', b'(\\HasNoChildren) "/" "Inbox"'])

    assert server._find_special_folder(_C(), server.DRAFTS_FOLDER_CANDIDATES) == "Draft"


def test_find_special_folder_flag_beats_name_order():
    # \Drafts flag sits on "Drafts" (plural); candidates list "Draft" first.
    # Selection must follow the special-use flag, not the name order.
    class _C:
        def list(self):
            return (
                "OK",
                [
                    b'(\\HasNoChildren) "/" "Draft"',
                    b'(\\Drafts \\HasNoChildren) "/" "Drafts"',
                ],
            )

    assert server._find_special_folder(_C(), ["Draft", "Drafts"], use_flag="\\Drafts") == "Drafts"
