"""実際の Git リポジトリと CLI による統合検証。"""

import json
import subprocess
import sys
from pathlib import Path

from conftest import commit, write

from agent_change_verifier.cli import main
from agent_change_verifier.repository import compare


def test_good_worktree_and_committed_head(repo: Path, capsys) -> None:
    write(repo, "src/app.py", "value = 1\n")
    base = commit(repo)
    write(repo, "src/app.py", "value = 2\n")
    write(repo, "tests/test_app.py", "async def test_value():\n    assert 2 == 2\n")
    write(
        repo,
        "criteria.toml",
        """
[[criteria]]
id = "file"
description = "実装が存在"
kind = "file_exists"
path = "src/app.py"
[[criteria]]
id = "contains"
description = "値が更新"
kind = "file_contains"
path = "src/app.py"
pattern = "value = 2"
[[criteria]]
id = "touch"
description = "実装を変更"
kind = "diff_touches"
pattern = "src/*"
[[criteria]]
id = "keep"
description = "ライセンスを維持"
kind = "diff_not_touches"
pattern = "LICENSE"
[[criteria]]
id = "tests"
description = "テストを追加"
kind = "test_added_for"
path = "src/*"
[[criteria]]
id = "command"
description = "構文を確認"
kind = "command"
command = ["python", "-m", "compileall", "-q", "src"]
""",
    )
    args = ["check", "--base", base, "--criteria", "criteria.toml", "--format", "json"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["commands_not_run"] == 1
    assert payload["criteria"][-1]["status"] == "not_run"
    head = commit(repo)
    write(repo, "src/app.py", "破損した作業ツリー")
    assert main([*args, "--head", head, "--run-commands"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert all(row["status"] == "passed" for row in payload["criteria"])
    assert not list(repo.glob(".acv-command-*"))


def test_bad_changes(repo: Path, capsys) -> None:
    write(repo, "tests/test_old.py", "def test_old():\n    assert 1 == 1\n")
    write(repo, "pyproject.toml", "[tool.coverage.report]\nfail_under = 90\n")
    base = commit(repo)
    (repo / "tests/test_old.py").unlink()
    write(
        repo,
        "tests/test_new.py",
        "import pytest\n" + "@pytest.mark.skip\ndef test_new():\n    assert True\n",
    )
    write(repo, "pyproject.toml", "[tool.coverage.report]\nfail_under = 10\n")
    assert main(["check", "--base", base, "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    ids = {finding["rule_id"] for finding in payload["findings"]}
    assert {
        "TEST_FILE_DELETED",
        "TEST_COUNT_DECREASED",
        "ASSERTION_DECREASED",
        "TEST_DISABLED",
        "EMPTY_ASSERTION",
        "COVERAGE_LOWERED",
    } <= ids
    assert all(
        finding["file"] and finding["line"] > 0 and finding["evidence"]
        for finding in payload["findings"]
    )


def test_warnings_threshold_and_text(repo: Path, capsys) -> None:
    write(repo, "app.py", "x = 1\n")
    base = commit(repo)
    write(repo, "app.py", "x = 1  # noqa\n")
    write(repo, "state.snap", "期待値\n")
    assert main(["check", "--base", base]) == 0
    assert "[warning] SUPPRESSION_ADDED" in capsys.readouterr().out
    assert main(["check", "--base", base, "--fail-on", "warning"]) == 1
    assert "不合格" in capsys.readouterr().out


def test_invalid_reference_and_criteria(repo: Path, capsys) -> None:
    write(repo, "app.py", "x = 1\n")
    commit(repo)
    assert main(["check", "--base", "missing", "--format", "json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert main(["check", "--base", "HEAD", "--criteria", "absent.toml"]) == 2
    assert "入力エラー" in capsys.readouterr().err


def test_deletion_rename_ignored_and_symlink(repo: Path) -> None:
    write(repo, ".gitignore", "ignored\n")
    write(repo, "tests/test_app.py", "def test_app(): pass\n")
    base = commit(repo)
    (repo / "tests/test_app.py").rename(repo / "tests/test_other.py")
    write(repo, "ignored", "無視する")
    (repo / "link").symlink_to("tests/test_other.py")
    changes = compare(repo, base, None)
    assert "ignored" not in changes.files
    assert "link" not in changes.files
    assert {c.path for c in changes.changes} == {"tests/test_app.py", "tests/test_other.py"}
    (repo / "link").unlink()
    head = commit(repo)
    assert {c.path for c in compare(repo, base, head).changes} == {
        "tests/test_app.py",
        "tests/test_other.py",
    }


def test_module_entrypoint(repo: Path) -> None:
    write(repo, "app.py", "x = 1\n")
    commit(repo)
    result = subprocess.run(
        [sys.executable, "-m", "agent_change_verifier.cli", "check", "--base", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "合格" in result.stdout
