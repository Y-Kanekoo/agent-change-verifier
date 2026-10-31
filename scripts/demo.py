"""一時リポジトリで良い変更と悪い変更を実演する。"""

import subprocess
import sys
import tempfile
from pathlib import Path


def write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    temporary = project / ".tmp"
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="demo-", dir=temporary) as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        write(root, "src/app.py", "value = 1\n")
        write(root, "tests/test_old.py", "def test_old():\n    assert 1 == 1\n")
        write(root, "coverage.toml", "fail_under = 90\n")
        write(root, "README.md", "準備中\n")
        write(
            root,
            "criteria.toml",
            """[[criteria]]
id = "ready"
description = "README に完了と記載されている"
kind = "file_contains"
path = "README.md"
pattern = "完了"

[[criteria]]
id = "tests"
description = "実装変更にテスト変更を伴う"
kind = "test_added_for"
path = "src/*"

[[criteria]]
id = "syntax"
description = "Python の構文を検証する"
kind = "command"
command = ["python", "-m", "compileall", "-q", "src"]
timeout = 10
""",
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=デモ",
                "-c",
                "user.email=demo@example.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "デモ用の比較元",
            ],
            check=True,
        )
        command = [
            sys.executable,
            "-m",
            "agent_change_verifier.cli",
            "check",
            "--base",
            "HEAD",
            "--criteria",
            "criteria.toml",
            "--run-commands",
        ]
        write(root, "src/app.py", "value = 2\n")
        write(root, "tests/test_new.py", "def test_new():\n    assert 2 == 2\n")
        write(root, "README.md", "完了\n")
        print("=== 良い変更 ===", flush=True)
        good = subprocess.run(command, cwd=root, check=False)
        print(f"終了コード: {good.returncode}", flush=True)
        (root / "tests/test_old.py").unlink()
        write(
            root,
            "tests/test_new.py",
            "import pytest\n"
            + "@pytest.mark.skip(reason='保留')\ndef test_new():\n    assert True\n",
        )
        write(root, "coverage.toml", "fail_under = 20\n")
        write(root, "README.md", "準備中\n")
        print("=== 悪い変更 ===", flush=True)
        bad = subprocess.run(command, cwd=root, check=False)
        print(f"終了コード: {bad.returncode}", flush=True)
        if good.returncode != 0 or bad.returncode != 1:
            print("デモの判定が期待と異なります。", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
