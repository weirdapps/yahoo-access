# yahoo-access

MCP server for Yahoo Mail (`imap.mail.yahoo.com` / `smtp.mail.yahoo.com`). IMAP read + SMTP send for the accounts configured in `~/.yahoo-mail/accounts.json` (keys such as `personal`, `work`), 13 `yahoo_*` tools. Fork-with-substitutions of `sch-mail`.

## Tech Stack

- Python 3.12+, single runtime dep `mcp[cli]>=2.0.0`; stdlib `imaplib`/`smtplib`/`email`/`ssl`/`subprocess`.
- Server object is `from mcp.server import MCPServer` (SDK v2), **not** the older `mcp.server.fastmcp.FastMCP`. The v2 `@mcp.tool()` decorator returns the plain function, so tests call `server.yahoo_list_mail(...)` directly (no `.fn` attribute).
- Dev: `pytest`, `ruff`. `pyproject.toml` sets `pythonpath = ["."]` so tests `import server`.
- `uv.lock` is committed and CI syncs `--frozen`: bump a dependency and you must relock in the same commit or CI fails.

## Install / Run / Test

```bash
uv sync --extra dev      # builds .venv from uv.lock (same as CI)
bash run_mcp.sh          # start server (normally launched by Claude Code)
.venv/bin/pytest -v      # 170 tests
.venv/bin/ruff check server.py tests/
```

`.venv` is gitignored; recreate if corrupted. The MCP server is normally registered with Claude Code as `yahoo-mail` (see README) and started on demand; run it manually only for debugging.

## Credentials

- App passwords in macOS Keychain (`security` CLI). Config map (no passwords) at `~/.yahoo-mail/accounts.json`, gitignored.
- Resolution order: Keychain → env `YAHOO_APP_PASSWORD_<KEY>` → inline `password`.
- Run `./setup.sh` once per account to store the app password and register it.
- Optional `~/.yahoo-mail/instructions.md` is appended to the generic MCP instructions at startup (`_build_instructions`). Installation-specific guidance (which accounts exist, house rules) goes there, never into `BASE_INSTRUCTIONS`, docstrings or docs: those use placeholder keys like `personal` / `work`.

## Key Conventions

- Fresh IMAP/SMTP connection per tool call, closed in `finally` — no pooling.
- All tools accept optional `account: str | None` (default: the account `accounts.json` marks as `default`).
- Draft-first: `send_now=False` APPENDs to Yahoo `Draft`; `send_now=True` dispatches via SMTP + archives to `Sent`.
- Draft/Sent targets are resolved by IMAP **special-use flag** (`\Drafts`/`\Sent`) first, then by name candidates. Yahoo's real special folders are singular `Draft` and `Sent`; a mailbox can also hold same-purpose folders without the flag, so name-only matching is unsafe.
- Message-ID domain is `yahoo.com`.
- Unicode (Greek) search falls back to client-side filtering over a 180-day window, and only headers are fetched: a non-ASCII query matches Subject and From only, so `field="body"` returns nothing and `field="all"` narrows to subject plus sender.
- Tools return dicts/lists. In-protocol failures (APPEND rejected, no recipients, folder missing) return `{"error": ...}`. Credential, config and connection failures are NOT caught: `_load_credentials` / `_connect` raise `FileNotFoundError`, `ValueError` or `imaplib.IMAP4.error` straight out of the tool, so callers cannot rely on always getting an `error` key. Only `yahoo_check_auth` catches broadly and reports per-account `ok`/`stage`/`error`/`hint`.
- All folder names passed to IMAP are quoted via `_q()` — handles spaces, quotes and backslashes. imaplib does not quote mailbox args itself.
- CR, LF and NUL are refused with `ValueError` in folder names (`_q`) and search queries (`_refuse_line_breaks`), and every tool that takes a `msg_id` returns an error unless it is one numeric UID (`_is_uid`): on Python 3.12 imaplib sends a line break inside an argument as given, which would start a second IMAP command. Search text goes out as an IMAP quoted string (backslash and quote escaped).
- Local paths are fenced: `_allowed_path` resolves symlinks and refuses anything outside `DEFAULT_ALLOWED_DIRS` (`~/Downloads`, the system temp dir, `/tmp`) or the `YAHOO_MAIL_ALLOWED_DIRS` list that replaces it. Keep the default that narrow: any file in an allowed folder can be attached to an outgoing message, so folders holding the user's own documents (Documents, Desktop, Library/CloudStorage) stay an explicit opt-in through the env var. A refused attachment makes `yahoo_send_mail` return an error before anything is saved or sent; a refused `out_dir` makes `yahoo_download_attachments` return one. Downloaded names never start with a dot.
- Sender-controlled content must never raise out of a tool or stall it. `_decode_bytes` falls back to UTF-8 when a declared charset is unknown or refuses `errors="replace"` (idna); `_decode_header` returns the raw header when an encoded-word will not decode (`HeaderParseError`), and `_get_filename` the undecoded name when `get_filename()` raises on an RFC 2231 charset; a header carrying raw 8-bit bytes comes back from `Message.get` as an `email.header.Header`, so `_parse_date` and `_disposition` turn it into `str` before testing or returning it; `_parse_message` returns None for a MIME tree too deep to walk, which get / download / forward report as an error; `_strip_html` stays linear (`tests/test_helpers.py` pins its output to the old regex version and bounds its time on hostile markup). `tests/test_hostile_messages.py` pins each case. Known gap: `yahoo_download_attachments` still raises when the file system refuses a sender-chosen attachment name (a NUL, an illegal byte sequence, too long), which fails that one download. Saved attachments are tagged `com.apple.quarantine` via `/usr/bin/xattr` (`_quarantine`, best effort, macOS only).
- Destructive ops are guarded: `yahoo_delete_mail` defaults to move-to-Trash (`permanent=True` = `\Deleted` + expunge of that one UID in place); `yahoo_empty_folder` is a dry-run reporting the count unless `confirm=True`.
- Message ids are IMAP UIDs everywhere (`conn.uid(...)`), never sequence numbers, which renumber on every expunge: list and search hand out UIDs; get, download, forward, move and delete take them. Move and soft-delete use UID MOVE when the post-login CAPABILITY has MOVE, else UID COPY + `\Deleted` + UID EXPUNGE (UIDPLUS), and a bare EXPUNGE only when the server has neither (`_expunge_uid` says why). Move and delete refuse anything but one numeric UID and report a UID that no longer exists as not found. `yahoo_empty_folder` is the one deliberate folder-wide `1:*` + EXPUNGE.

## Prerequisite Gotcha

Yahoo IMAP must be enabled per account (Settings → More Settings → Mailboxes → IMAP) or every login fails with an auth error even when the app password is correct. `yahoo_check_auth` returns a hint pointing at this.

## Code Organization

Single-file (`server.py`): constants + `_build_instructions` + the `MCPServer` → local file access (`_allowed_dirs`, `_allowed_path`, `_quarantine`) → credential loader → connection helpers + `yahoo_check_auth` → parsing helpers → read tools → send helpers → write tools → `__main__`.
