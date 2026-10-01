import random
import re
import time
from datetime import datetime

import pytest

import server


def _strip_html_regex(html: str) -> str:
    """The previous _strip_html, kept as the oracle the linear version must match."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def test_strip_html_removes_tags_and_scripts():
    html = "<style>x{}</style><p>Hello</p><br><script>bad()</script>World"
    out = server._strip_html(html)
    assert "Hello" in out and "World" in out
    assert "<" not in out and "bad()" not in out


@pytest.mark.parametrize(
    "html",
    [
        "<html><head><STYLE type='text/css'>p{color:red}</STYLE></head>"
        "<body><p>One</p><p>Two<br/>Three</p><!-- note --></body></html>",
        "<Script>a()</SCRIPT>keep<script src=x></script>",
        "<style>unclosed {",
        "<style</style>text",
        "a <> b < c > d",
        "<<a>>",
        "x < y and y > z",
        "<style>a</style><style>b",
        "line1\n\n\n\nline2<br><br><br>",
        "",
    ],
)
def test_strip_html_matches_the_regex_version(html):
    assert server._strip_html(html) == _strip_html_regex(html)


def test_strip_html_matches_the_regex_version_on_random_markup():
    tokens = ["<", ">", "<>", "/", "a", " ", "\n", "<p>", "</p>", "</P>", "<br>", "<BR />"]
    tokens += ["<style", "<STYLE media=x>", "</style>", "</Style>", "<script>", "</script>"]
    rng = random.Random(20261001)
    for _ in range(5000):
        html = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 25)))
        assert server._strip_html(html) == _strip_html_regex(html), repr(html)


@pytest.mark.parametrize(
    "html",
    [
        pytest.param("<style>" * 30_000, id="unclosed-style"),
        pytest.param("<script>" * 30_000, id="unclosed-script"),
        pytest.param("<style" * 30_000, id="opener-without-gt"),
        pytest.param("<" * 200_000, id="bare-lt"),
    ],
)
def test_strip_html_stays_fast_on_hostile_markup(html):
    # About 200 KB each. The regex version spends tens of seconds on every one.
    start = time.perf_counter()
    server._strip_html(html)
    assert time.perf_counter() - start < 2


def test_decode_header_plain():
    assert server._decode_header("Simple Subject") == "Simple Subject"


def test_decode_header_encoded():
    # =?UTF-8?B?zpPOtc65zqw=?= is base64 "Γειά"
    assert "Γειά" in server._decode_header("=?UTF-8?B?zpPOtc65zqw=?=")


def test_imap_date_format():
    assert server._imap_date(datetime(2026, 7, 1)) == "01-Jul-2026"


def test_guess_mime_pdf():
    assert server._guess_mime("report.pdf") == "application/pdf"
