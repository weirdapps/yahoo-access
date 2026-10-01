"""MCP instructions: a generic base text, plus an optional local file.

Which accounts exist, and any house rules for a mailbox, belong to one
installation, so they live in ~/.yahoo-mail/instructions.md rather than in the repo.
"""

import os
import subprocess
import sys
from pathlib import Path

import server

REPO = Path(__file__).resolve().parent.parent


def test_without_a_local_file_the_instructions_are_the_base_text(tmp_path):
    assert server._build_instructions(tmp_path / "instructions.md") == server.BASE_INSTRUCTIONS


def test_a_local_file_is_appended_to_the_base_text(tmp_path):
    local = tmp_path / "instructions.md"
    local.write_text("Accounts: 'personal' (default) and 'work'.\n", encoding="utf-8")

    assert server._build_instructions(local) == (
        server.BASE_INSTRUCTIONS + "\n\nAccounts: 'personal' (default) and 'work'."
    )


def test_a_blank_local_file_adds_nothing(tmp_path):
    local = tmp_path / "instructions.md"
    local.write_text("  \n\n", encoding="utf-8")

    assert server._build_instructions(local) == server.BASE_INSTRUCTIONS


def test_an_unreadable_local_file_falls_back_to_the_base_text(tmp_path, capsys):
    local = tmp_path / "instructions.md"
    local.write_bytes(b"\xff\xfe not utf-8")

    assert server._build_instructions(local) == server.BASE_INSTRUCTIONS
    assert "ignoring" in capsys.readouterr().err


def test_the_local_file_sits_next_to_accounts_json():
    assert server.INSTRUCTIONS_PATH == server.CONFIG_PATH.parent / "instructions.md"


def test_the_server_reads_the_local_file_at_startup(tmp_path):
    # A fresh interpreter with HOME pointed at tmp_path, so the module-level MCPServer
    # is built exactly as it is when a client launches the server.
    config_dir = tmp_path / ".yahoo-mail"
    config_dir.mkdir()
    (config_dir / "instructions.md").write_text("Local note.\n", encoding="utf-8")

    out = subprocess.run(
        [sys.executable, "-c", "import server; print(server.mcp.instructions)"],
        cwd=REPO,
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    assert out.stdout.rstrip("\n") == server.BASE_INSTRUCTIONS + "\n\nLocal note."
