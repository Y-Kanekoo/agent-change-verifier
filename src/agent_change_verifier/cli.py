"""日本語テキストと JSON を出力する CLI。"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from .criteria import evaluate, load
from .repository import VerificationError, compare
from .rules import inspect


class JapaneseParser(argparse.ArgumentParser):
    """引数の検証エラーを日本語で報告する。"""

    def error(self, message: str) -> NoReturn:
        self.exit(
            2, "引数エラー: 必須引数の不足または不正な値があります。--help を確認してください。\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = JapaneseParser(description="エージェントの変更を検証します。")
    subparsers = parser.add_subparsers(dest="action", required=True)
    check = subparsers.add_parser("check", help="差分と受け入れ条件を検証")
    check.add_argument("--base", required=True, help="比較元の Git 参照")
    check.add_argument("--head", help="比較先の Git 参照（省略時は作業ツリー）")
    check.add_argument("--criteria", type=Path, help="受け入れ条件の TOML")
    check.add_argument("--run-commands", action="store_true", help="条件のコマンド実行を許可")
    check.add_argument("--format", choices=("text", "json"), default="text", help="出力形式")
    check.add_argument(
        "--fail-on", choices=("error", "warning"), default="error", help="不合格とする重大度の閾値"
    )
    args = parser.parse_args(argv)
    try:
        conditions = load(args.criteria) if args.criteria else []
        comparison = compare(Path.cwd(), args.base, args.head)
        findings = inspect(comparison.changes)
        results = evaluate(conditions, comparison, args.run_commands)
    except (VerificationError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, VerificationError)
            else "ファイル操作に失敗しました。権限とパスを確認してください。"
        )
        if args.format == "json":
            print(json.dumps({"passed": False, "error": message}, ensure_ascii=False))
        else:
            print(f"入力エラー: {message}", file=sys.stderr)
        return 2
    levels = {"error", "warning"} if args.fail_on == "warning" else {"error"}
    failed = any(f.severity in levels for f in findings) or any(
        r.status == "failed" and r.severity in levels for r in results
    )
    payload = {
        "passed": not failed,
        "fail_on": args.fail_on,
        "changed_files": [change.path for change in comparison.changes],
        "renamed_files": [{"from": old, "to": new} for old, new in comparison.renames],
        "findings": [asdict(finding) for finding in findings],
        "criteria": [asdict(result) for result in results],
        "commands_not_run": sum(result.status == "not_run" for result in results),
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"判定: {'不合格' if failed else '合格'}（変更 {len(comparison.changes)} ファイル）")
        for old, new in comparison.renames:
            print(f"移動: {old} → {new}（移動前の内容と比べて検査）")
        for finding in findings:
            print(
                f"[{finding.severity}] {finding.rule_id} {finding.file}:{finding.line} {finding.message}"
            )
            print(f"  根拠: {finding.evidence}")
        labels = {"passed": "合格", "failed": "不合格", "not_run": "未実行"}
        for result in results:
            print(f"[条件:{labels[result.status]}] {result.id} {result.description}")
            print(f"  根拠: {result.evidence}")
        if payload["commands_not_run"]:
            print("注意: 未実行のコマンド条件があります。受け入れ条件すべての合格は未確認です。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
