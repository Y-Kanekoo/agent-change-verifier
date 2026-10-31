"""Git の rename 検出による、テストの移動・改名の扱いの検証。"""

import json
import subprocess
from pathlib import Path

from conftest import commit, write

from agent_change_verifier.cli import main
from agent_change_verifier.repository import compare, parse_renames

TESTS = "def test_one():\n    assert 1 == 1\n\n\ndef test_two():\n    assert 2 == 2\n\n\ndef test_three():\n    assert 3 == 3\n"


def findings(capsys, *args: str) -> tuple[int, dict]:
    code = main(["check", *args, "--format", "json"])
    return code, json.loads(capsys.readouterr().out)


def test_parse_renames_skips_other_statuses() -> None:
    output = b"M\0src/app.py\0R100\0tests/a.py\0tests/unit/a.py\0D\0old.py\0"
    assert parse_renames(output) == {"tests/a.py": "tests/unit/a.py"}
    assert parse_renames(b"") == {}


def test_worktree_move_is_not_deletion(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True)
    (repo / "tests/unit").mkdir()
    (repo / "tests/test_app.py").rename(repo / "tests/unit/test_app.py")
    code, payload = findings(capsys, "--base", base)
    assert code == 0
    assert payload["findings"] == []
    assert payload["renamed_files"] == [
        {"from": "tests/test_app.py", "to": "tests/unit/test_app.py"}
    ]
    assert set(payload["changed_files"]) == {"tests/test_app.py", "tests/unit/test_app.py"}
    # 本来のインデックスを変えず、一時インデックスを残さない。
    assert subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True) == staged
    assert not list((repo / ".git").glob("acv-index-*"))


def test_committed_move_is_not_deletion(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    (repo / "tests/test_app.py").rename(repo / "tests/test_renamed.py")
    head = commit(repo)
    assert compare(repo, base, head).renames == [("tests/test_app.py", "tests/test_renamed.py")]
    code, payload = findings(capsys, "--base", base, "--head", head)
    assert code == 0
    assert payload["findings"] == []
    assert main(["check", "--base", base, "--head", head]) == 0
    assert "移動: tests/test_app.py → tests/test_renamed.py" in capsys.readouterr().out


def test_move_with_fewer_tests_is_reported(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    (repo / "tests/test_app.py").unlink()
    write(
        repo,
        "tests/unit/test_app.py",
        "import pytest\n\n\ndef test_one():\n    assert 1 == 1\n\n\n"
        "@pytest.mark.skip\ndef test_two():\n    assert 2 == 2\n",
    )
    code, payload = findings(capsys, "--base", base)
    assert code == 1
    assert payload["renamed_files"] == [
        {"from": "tests/test_app.py", "to": "tests/unit/test_app.py"}
    ]
    rules = {(f["rule_id"], f["file"]) for f in payload["findings"]}
    assert rules == {
        ("TEST_COUNT_DECREASED", "tests/unit/test_app.py"),
        ("ASSERTION_DECREASED", "tests/unit/test_app.py"),
        ("TEST_DISABLED", "tests/unit/test_app.py"),
    }


def test_move_out_of_test_paths_is_deletion(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    (repo / "docs").mkdir()
    (repo / "tests/test_app.py").rename(repo / "docs/example.py")
    code, payload = findings(capsys, "--base", base)
    assert code == 1
    deleted = [f for f in payload["findings"] if f["rule_id"] == "TEST_FILE_DELETED"]
    assert len(deleted) == 1
    assert deleted[0]["file"] == "tests/test_app.py"
    assert "docs/example.py へ移動" in deleted[0]["evidence"]


def test_rewritten_test_is_still_deletion(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    (repo / "tests/test_app.py").unlink()
    write(repo, "tests/test_other.py", "def test_other():\n    assert 'x' in 'xyz'\n")
    code, payload = findings(capsys, "--base", base)
    assert code == 1
    assert payload["renamed_files"] == []
    assert "TEST_FILE_DELETED" in {f["rule_id"] for f in payload["findings"]}


def test_worktree_without_index(repo: Path, capsys) -> None:
    write(repo, "tests/test_app.py", TESTS)
    base = commit(repo)
    (repo / ".git/index").unlink()
    (repo / "tests/test_app.py").rename(repo / "tests/test_moved.py")
    code, payload = findings(capsys, "--base", base)
    assert code == 0
    assert payload["renamed_files"] == [{"from": "tests/test_app.py", "to": "tests/test_moved.py"}]
    assert not (repo / ".git/index").exists()
