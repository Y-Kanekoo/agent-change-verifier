"""Git の比較対象を読み取り、作業ツリーを変更せずに差分を作る。"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class VerificationError(Exception):
    """入力やリポジトリの検証に失敗した。"""


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise VerificationError("Git コマンドに失敗しました。参照とリポジトリを確認してください。")
    return result.stdout


def resolve(root: Path, ref: str) -> str:
    return (
        git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    )


def safe_path(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts and ".git" not in path.parts


def snapshot(root: Path, ref: str | None) -> dict[str, bytes]:
    if ref is not None:
        names = git(root, "ls-tree", "-rz", "--name-only", ref).split(b"\0")
    else:
        names = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(
            b"\0"
        )
    files: dict[str, bytes] = {}
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        if not safe_path(name):
            raise VerificationError("安全に扱えないファイルパスがあります。")
        if ref is not None:
            # サブモジュールはファイルとして扱わない。
            kind = git(root, "cat-file", "-t", f"{ref}:{name}").strip()
            if kind == b"blob":
                files[name] = git(root, "show", f"{ref}:{name}")
        else:
            path = root / name
            if path.is_file() and not path.is_symlink():
                files[name] = path.read_bytes()
    return files


@dataclass(frozen=True)
class Change:
    path: str
    before: str
    after: str
    deleted: bool


@dataclass(frozen=True)
class Comparison:
    root: Path
    files: dict[str, bytes]
    changes: list[Change]


def compare(cwd: Path, base: str, head: str | None) -> Comparison:
    root = Path(git(cwd, "rev-parse", "--show-toplevel").decode().strip())
    before = snapshot(root, resolve(root, base))
    after = snapshot(root, resolve(root, head) if head is not None else None)
    changes = [
        Change(
            name,
            before.get(name, b"").decode("utf-8", errors="replace"),
            after.get(name, b"").decode("utf-8", errors="replace"),
            name not in after,
        )
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    ]
    return Comparison(root, after, changes)
