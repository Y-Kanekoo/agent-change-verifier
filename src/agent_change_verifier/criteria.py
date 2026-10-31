"""TOML の受け入れ条件を検証・評価する。"""

import math
import os
import re
import signal
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from .models import CriterionResult, Severity, Status
from .repository import Comparison, VerificationError, safe_path
from .rules import is_test


@dataclass(frozen=True)
class Criterion:
    id: str
    description: str
    kind: str
    severity: Severity
    path: str = ""
    pattern: str = ""
    command: tuple[str, ...] = ()
    timeout: float = 30


def required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"受け入れ条件の {key} は空でない文字列が必要です。")
    return value


def load(path: Path) -> list[Criterion]:
    try:
        with path.open("rb") as stream:
            data: dict[str, object] = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise VerificationError("受け入れ条件の TOML を読み込めません。") from error
    rows = data.get("criteria")
    if not isinstance(rows, list) or not rows:
        raise VerificationError("[[criteria]] を1件以上指定してください。")
    conditions: list[Criterion] = []
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise VerificationError("受け入れ条件はテーブルで指定してください。")
        identifier = required_string(row, "id")
        description = required_string(row, "description")
        kind = required_string(row, "kind")
        if identifier in ids:
            raise VerificationError(f"受け入れ条件の id が重複しています: {identifier}")
        ids.add(identifier)
        severity = row.get("severity", "error")
        if severity not in ("error", "warning"):
            raise VerificationError("severity は error または warning を指定してください。")
        level: Severity = "warning" if severity == "warning" else "error"
        target, pattern = "", ""
        command: tuple[str, ...] = ()
        timeout = 30.0
        if kind in {"file_exists", "file_contains", "test_added_for"}:
            target = required_string(row, "path")
            if not safe_path(target):
                raise VerificationError("path はリポジトリ内の相対パスで指定してください。")
        if kind in {"diff_touches", "diff_not_touches", "file_contains"}:
            pattern = required_string(row, "pattern")
            if kind == "file_contains":
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise VerificationError("file_contains の正規表現が不正です。") from error
        if kind == "command":
            argv = row.get("command")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(v, str) and v for v in argv)
            ):
                raise VerificationError("command は空でない文字列の配列で指定してください。")
            command = tuple(str(value) for value in argv)
            seconds = row.get("timeout", 30)
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
                raise VerificationError("timeout は正の有限秒数で指定してください。")
            timeout = float(seconds)
            if not math.isfinite(timeout) or timeout <= 0:
                raise VerificationError("timeout は正の有限秒数で指定してください。")
        elif kind not in {
            "file_exists",
            "file_contains",
            "diff_touches",
            "diff_not_touches",
            "test_added_for",
        }:
            raise VerificationError(f"未対応の検査種別です: {kind}")
        conditions.append(
            Criterion(identifier, description, kind, level, target, pattern, command, timeout)
        )
    return conditions


def run_command(condition: Criterion, comparison: Comparison) -> tuple[bool, str]:
    # コピー先もリポジトリ内に限定し、終了時に削除する。
    with tempfile.TemporaryDirectory(prefix=".acv-command-", dir=comparison.root) as directory:
        root = Path(directory)
        for name, content in comparison.files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        try:
            with subprocess.Popen(
                condition.command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as process:
                try:
                    output, _ = process.communicate(timeout=condition.timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    return False, f"タイムアウト（{condition.timeout:g} 秒）"
                detail = output.decode("utf-8", errors="replace")[-4000:].strip()
                return process.returncode == 0, f"終了コード {process.returncode}" + (
                    f"\n{detail}" if detail else ""
                )
        except OSError:
            return False, "コマンドを起動できません。実行ファイルを確認してください。"


def evaluate(
    conditions: list[Criterion], comparison: Comparison, run: bool
) -> list[CriterionResult]:
    results: list[CriterionResult] = []
    paths = [change.path for change in comparison.changes]
    tests_changed = any(
        is_test(change.path) and not change.deleted for change in comparison.changes
    )
    for condition in conditions:
        status: Status = "passed"
        passed = True
        evidence = ""
        if condition.kind == "command":
            if not run:
                status, evidence = "not_run", "未実行（--run-commands が必要です）"
            else:
                passed, evidence = run_command(condition, comparison)
        elif condition.kind in {"file_exists", "file_contains"}:
            content = comparison.files.get(condition.path)
            passed = content is not None
            if condition.kind == "file_contains":
                passed = (
                    content is not None
                    and re.search(
                        condition.pattern, content.decode("utf-8", errors="replace"), re.MULTILINE
                    )
                    is not None
                )
            evidence = f"対象: {condition.path}" + (
                f" / 正規表現: {condition.pattern}" if condition.pattern else ""
            )
        elif condition.kind in {"diff_touches", "diff_not_touches"}:
            matches = [path for path in paths if fnmatchcase(path, condition.pattern)]
            passed = bool(matches) if condition.kind == "diff_touches" else not matches
            evidence = f"glob: {condition.pattern} / 一致: {', '.join(matches) or 'なし'}"
        elif condition.kind == "test_added_for":
            triggered = any(fnmatchcase(path, condition.path) for path in paths)
            passed = not triggered or tests_changed
            evidence = f"対象変更: {'あり' if triggered else 'なし'} / テスト追加・変更: {'あり' if tests_changed else 'なし'}"
        if not passed:
            status = "failed"
        results.append(
            CriterionResult(
                condition.id,
                condition.description,
                condition.kind,
                status,
                evidence,
                condition.severity,
            )
        )
    return results
