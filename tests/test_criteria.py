"""受け入れ条件の入力検証と実行結果を検証する。"""

import sys
from pathlib import Path

import pytest

from agent_change_verifier.criteria import Criterion, evaluate, load
from agent_change_verifier.repository import Change, Comparison, VerificationError, safe_path


@pytest.mark.parametrize(
    "content",
    [
        "broken = [",
        "",
        "criteria = []",
        "criteria = [1]",
        '[[criteria]]\nid = "a"',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "unknown"',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "file_exists"\npath = "../outside"',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "file_contains"\npath = "a"\npattern = "["',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "command"\ncommand = "python"',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "command"\ncommand = ["python"]\ntimeout = -1',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "command"\ncommand = ["python"]\ntimeout = true',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "command"\ncommand = ["python"]\ntimeout = inf',
        '[[criteria]]\nid = "a"\ndescription = "例"\nkind = "file_exists"\npath = "a"\nseverity = "info"',
        ('[[criteria]]\nid = "a"\ndescription = "例"\nkind = "file_exists"\npath = "a"\n' * 2),
    ],
)
def test_invalid_criteria(tmp_path: Path, content: str) -> None:
    path = tmp_path / "criteria.toml"
    path.write_text(content)
    with pytest.raises(VerificationError):
        load(path)


def test_failed_and_vacuous_conditions(tmp_path: Path) -> None:
    conditions = [
        Criterion("file", "例", "file_exists", "error", path="missing"),
        Criterion("contains", "例", "file_contains", "error", path="file", pattern="expected"),
        Criterion("touch", "例", "diff_touches", "error", pattern="absent/*"),
        Criterion("keep", "例", "diff_not_touches", "error", pattern="src/*"),
        Criterion("test", "例", "test_added_for", "error", path="src/*"),
        Criterion("nochange", "例", "test_added_for", "error", path="other/*"),
    ]
    comparison = Comparison(tmp_path, {"file": b"wrong"}, [Change("src/app.py", "", "x", False)])
    results = evaluate(conditions, comparison, False)
    assert [r.status for r in results] == ["failed"] * 5 + ["passed"]


@pytest.mark.parametrize(
    "argv,timeout,status,detail",
    [
        ((sys.executable, "-c", "print('成功')"), 10, "passed", "成功"),
        ((sys.executable, "-c", "raise SystemExit(3)"), 10, "failed", "終了コード 3"),
        ((sys.executable, "-c", "import time; time.sleep(10)"), 0.02, "failed", "タイムアウト"),
        (("/実在しないコマンド",), 10, "failed", "起動できません"),
    ],
)
def test_commands(
    tmp_path: Path, argv: tuple[str, ...], timeout: float, status: str, detail: str
) -> None:
    comparison = Comparison(tmp_path, {"src/file": b"content"}, [])
    condition = Criterion("command", "例", "command", "error", command=argv, timeout=timeout)
    result = evaluate([condition], comparison, True)[0]
    assert result.status == status
    assert detail in result.evidence
    assert list(tmp_path.iterdir()) == []


def test_paths_and_warning(tmp_path: Path) -> None:
    assert not safe_path("/absolute")
    assert not safe_path(".git/config")
    path = tmp_path / "criteria.toml"
    path.write_text(
        '[[criteria]]\nid="a"\ndescription="例"\nkind="file_exists"\npath="a"\nseverity="warning"'
    )
    assert load(path)[0].severity == "warning"
