"""文書と実装コードの境界を検証する。"""

from pathlib import Path

from conftest import commit, write

from agent_change_verifier.cli import main
from agent_change_verifier.repository import Change
from agent_change_verifier.rules import inspect


def test_documentation_patterns_are_not_code() -> None:
    assert not inspect([Change("README.md", "", "pytest.mark.skip\n# noqa\n", False)])


def test_assertion_with_message() -> None:
    findings = inspect([Change("test_app.py", "", "assert True, '仮の検査'", False)])
    assert findings[0].rule_id == "EMPTY_ASSERTION"


def test_not_run_is_explicit_in_text(repo: Path, capsys) -> None:
    write(repo, "app.py", "value = 1\n")
    commit(repo)
    write(
        repo,
        "criteria.toml",
        """[[criteria]]
id = "command"
description = "未実行の条件"
kind = "command"
command = ["実行してはいけないコマンド"]
""",
    )
    assert main(["check", "--base", "HEAD", "--criteria", "criteria.toml"]) == 0
    assert "未実行のコマンド条件" in capsys.readouterr().out
