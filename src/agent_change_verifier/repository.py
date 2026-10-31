"""Git の比較対象を読み取り、作業ツリーを変更せずに差分を作る。"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class VerificationError(Exception):
    """入力やリポジトリの検証に失敗した。"""


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False, env=env
    )
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


RENAME_DIFF = ("diff", "-z", "--name-status", "-M", "--diff-filter=R", "--no-ext-diff")


def parse_renames(output: bytes) -> dict[str, str]:
    """`git diff -z --name-status` の出力から、移動元と移動先の対応を返す。"""
    fields = output.split(b"\0")
    pairs: dict[str, str] = {}
    index = 0
    while index + 2 < len(fields):
        status = fields[index]
        if status.startswith(b"R"):
            old = fields[index + 1].decode("utf-8", errors="surrogateescape")
            new = fields[index + 2].decode("utf-8", errors="surrogateescape")
            pairs[old] = new
            index += 3
        else:
            index += 2
    return pairs


def renames(root: Path, base: str, head: str | None) -> dict[str, str]:
    """Git の rename 検出（既定の類似度 50%）で、移動・改名されたファイルを返す。"""
    if head is not None:
        return parse_renames(git(root, *RENAME_DIFF, base, head))
    # 作業ツリーは未追跡ファイルも比較対象なので、一時インデックスへ登録して比較する。
    # 本来のインデックスと作業ツリーは変更しない。
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    handle, name = tempfile.mkstemp(prefix="acv-index-", dir=git_dir)
    os.close(handle)
    temporary = Path(name)
    try:
        index = Path(
            git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()
        )
        if index.is_file():
            shutil.copyfile(index, temporary)
        else:
            temporary.unlink()
        env = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
        git(root, "add", "-A", "--", ".", env=env)
        return parse_renames(git(root, *RENAME_DIFF, "--cached", base, env=env))
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Change:
    path: str
    before: str
    after: str
    deleted: bool
    # 移動・改名の場合だけ設定する。移動先の Change の before は移動元の内容。
    renamed_from: str | None = None
    renamed_to: str | None = None


@dataclass(frozen=True)
class Comparison:
    root: Path
    files: dict[str, bytes]
    changes: list[Change]

    @property
    def renames(self) -> list[tuple[str, str]]:
        return [(c.renamed_from, c.path) for c in self.changes if c.renamed_from is not None]


def compare(cwd: Path, base: str, head: str | None) -> Comparison:
    root = Path(git(cwd, "rev-parse", "--show-toplevel").decode().strip())
    base_commit = resolve(root, base)
    head_commit = resolve(root, head) if head is not None else None
    before = snapshot(root, base_commit)
    after = snapshot(root, head_commit)
    moved = {
        old: new
        for old, new in renames(root, base_commit, head_commit).items()
        if old in before and old not in after and new in after and new not in before
    }
    origin = {new: old for old, new in moved.items()}

    def decode(data: bytes | None) -> str:
        return (data or b"").decode("utf-8", errors="replace")

    changes: list[Change] = []
    for name in sorted(before.keys() | after.keys()):
        if name in origin:
            source = origin[name]
            changes.append(
                Change(
                    name, decode(before[source]), decode(after[name]), False, renamed_from=source
                )
            )
        elif before.get(name) != after.get(name):
            changes.append(
                Change(
                    name,
                    decode(before.get(name)),
                    decode(after.get(name)),
                    name not in after,
                    renamed_to=moved.get(name),
                )
            )
    return Comparison(root, after, changes)
