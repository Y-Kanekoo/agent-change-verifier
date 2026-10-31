"""言語別のパターンを使った差分のヒューリスティック検査。"""

import difflib
import re
from pathlib import PurePosixPath

from .models import Finding, Severity
from .repository import Change

# 対応言語はこの表に追加できる。
TEST_PATTERNS = {
    ".py": r"^\s*(?:async\s+)?def\s+test_\w+\s*\(",
    ".js": r"\b(?:it|test)\s*(?:\.\s*(?:skip|only|todo))?\s*\(",
}
for suffix in (".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
    TEST_PATTERNS[suffix] = TEST_PATTERNS[".js"]

SKIP = re.compile(
    r"pytest\s*\.\s*mark\s*\.\s*(?:skipif|skip|xfail)\b|"
    r"pytest\s*\.\s*(?:skip|xfail)\s*\(|"
    r"\b(?:it|test|describe)\s*\.\s*(?:skip|only|todo)\b|\b(?:xit|xtest|xdescribe)\s*\("
)
SUPPRESSION = re.compile(
    r"#\s*(?:noqa\b|type:\s*ignore\b)|eslint-disable|@ts-(?:ignore|expect-error)\b"
)
EMPTY_ASSERTION = re.compile(r"\bassert\s+(?:True|1)\s*(?:$|#|,)|\bexpect\s*\(\s*true\s*\)")
ASSERTION = re.compile(r"\bassert\b|\b(?:expect|assert\w*)\s*\(")
THRESHOLD = re.compile(
    r"(?P<key>--cov-fail-under|--fail-under|fail_under|statements|branches|functions|lines)"
    r"[\s\"']*[:=\s]\s*(?P<value>\d+(?:\.\d+)?)"
)


def is_test(path: str) -> bool:
    file = PurePosixPath(path)
    return file.suffix in TEST_PATTERNS and (
        file.name.startswith("test_")
        or file.stem.endswith("_test")
        or ".test." in file.name
        or ".spec." in file.name
        or bool({"tests", "test", "__tests__"} & set(file.parts[:-1]))
    )


def added_lines(change: Change) -> list[tuple[int, str]]:
    before, after = change.before.splitlines(), change.after.splitlines()
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    return [
        (index + 1, after[index])
        for tag, _, _, start, end in matcher.get_opcodes()
        if tag in ("insert", "replace")
        for index in range(start, end)
    ]


def thresholds(text: str) -> dict[tuple[str, int], tuple[float, int, str]]:
    values: dict[tuple[str, int], tuple[float, int, str]] = {}
    counts: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        for match in THRESHOLD.finditer(line):
            key = match["key"]
            if (
                key in {"statements", "branches", "functions", "lines"}
                and "coverageThreshold" not in text
            ):
                continue
            index = counts.get(key, 0)
            counts[key] = index + 1
            values[key, index] = (float(match["value"]), number, line.strip())
    return values


def inspect(changes: list[Change]) -> list[Finding]:
    findings: list[Finding] = []
    for change in changes:

        def emit(
            rule: str,
            line: int,
            message: str,
            evidence: str,
            severity: Severity = "error",
            path: str = change.path,
        ) -> None:
            findings.append(Finding(rule, severity, path, line, message, evidence))

        if change.renamed_to is not None and not (
            is_test(change.path) and not is_test(change.renamed_to)
        ):
            # 移動元は、移動先の Change で移動前の内容と比べて検査する。
            # テストがテストとして検出されないパスへ移った場合だけ、削除として扱う。
            continue
        is_source = PurePosixPath(change.path).suffix in TEST_PATTERNS
        test = is_test(change.path)
        if test and change.deleted:
            evidence = (
                f"{change.renamed_to} へ移動（テストとして検出されないパス）"
                if change.renamed_to is not None
                else "削除前のファイル全体"
            )
            emit("TEST_FILE_DELETED", 1, "テストファイルが削除されました。", evidence)
        if test:
            pattern = TEST_PATTERNS[PurePosixPath(change.path).suffix]
            for rule, expression, message in (
                ("TEST_COUNT_DECREASED", pattern, "テストケース数が減少しました。"),
                ("ASSERTION_DECREASED", ASSERTION.pattern, "アサーション数が減少しました。"),
            ):
                old = len(re.findall(expression, change.before, re.MULTILINE))
                new = len(re.findall(expression, change.after, re.MULTILINE))
                if new < old:
                    old_lines = change.before.splitlines()
                    old_line = next(
                        (i for i, value in enumerate(old_lines, 1) if re.search(expression, value)),
                        1,
                    )
                    emit(rule, old_line, message, f"{old} → {new}（削除前の行番号）")
        for number, line in added_lines(change):
            if is_source and SKIP.search(line):
                emit(
                    "TEST_DISABLED",
                    number,
                    "テストの無効化・実行限定が追加されました。",
                    line.strip(),
                )
            if test and EMPTY_ASSERTION.search(line):
                emit("EMPTY_ASSERTION", number, "空のアサーションが追加されました。", line.strip())
            if is_source and SUPPRESSION.search(line):
                emit(
                    "SUPPRESSION_ADDED",
                    number,
                    "lint・型検査の抑制が追加されました。",
                    line.strip(),
                    "warning",
                )
        old_thresholds = thresholds(change.before)
        for key, (value, number, source) in thresholds(change.after).items():
            if key in old_thresholds and value < old_thresholds[key][0]:
                emit("COVERAGE_LOWERED", number, "カバレッジ閾値が引き下げられました。", source)
        if change.path.endswith((".snap", ".snapshot")):
            emit(
                "SNAPSHOT_UPDATED",
                1,
                "スナップショットの期待値が変更されました。",
                "差分を人間が確認してください。",
                "warning",
            )
    return findings
