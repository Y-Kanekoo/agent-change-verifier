# agent-change-verifier

AI コーディングエージェントが作った Git 差分を検証し、人間のレビュー前にテストの削除・弱体化と受け入れ条件の不充足を見つける、小さな CLI です。

A small, dependency-free Python CLI that checks agent-generated Git changes for test removal, weakened safeguards, and acceptance criteria. Human review is still required.

Python 3.11 以上、Git、uv が必要です。ランタイムの外部 Python 依存はありません。現在のコマンド実行は macOS / Linux（POSIX）向けです。

## インストール

```sh
uv tool install git+https://github.com/Y-Kanekoo/agent-change-verifier
acv --help
# 同じコマンドを agent-change-verifier という名前でも利用可能
```

## 使い方

検証したい Git リポジトリ内で実行します。

```sh
# 比較元と現在の作業ツリー（ステージ済み・未ステージ・未追跡）を比較
acv check --base origin/main

# 2つのコミットの内容を比較
acv check --base origin/main --head HEAD

# 受け入れ条件も確認。command 条件の実行には明示的な許可が必要
acv check --base origin/main --criteria examples/criteria.toml --run-commands

# 警告も不合格にする / 機械向け出力
acv check --base origin/main --fail-on warning --format json
```

- `--head` の省略が「作業ツリー」です。文字列の `作業ツリー` を引数には渡しません。
- 比較は base と head の内容の直接比較です。merge-base や三点比較ではありません。
- 終了コード: `0`＝指定閾値の問題なし、`1`＝検出・条件不合格、`2`＝入力・Git・ファイル操作エラー。
- `--fail-on error` が既定です。`warning` を選ぶと error と warning の両方で終了コード 1 になります。
- `--criteria` を省略すると差分ルールだけを検査します。条件ファイルは自動実行されません。
- `--run-commands` なしの command 条件は `未実行` / JSON の `not_run` と表示されます。未実行だけでは不合格になりません。受け入れ条件の完全な確認には `--run-commands` と全条件の `passed` を確認してください。
- 条件ファイルの相対パスは CLI の実行位置基準、条件内のファイルパスはリポジトリのルート基準です。条件ファイル自体は呼び出し側のファイルを読みます（`--head` 内の版は自動選択しません）。

JSON には `passed`、`fail_on`、`changed_files`、`findings`、`criteria`、`commands_not_run` を出力します。検出には `rule_id`、`severity`、`file`、`line`、`message`、`evidence`、条件結果には `id`、`description`、`kind`、`status`、`evidence`、`severity` が入ります。入力エラー時は `passed: false` と `error` を出力します。

## 検査ルール

| ID | 重大度 | 検査 |
| --- | --- | --- |
| `TEST_FILE_DELETED` | error | テストファイルの削除 |
| `TEST_COUNT_DECREASED` | error | Python の `def test_` / `async def test_`、JS/TS の `it()` / `test()` の数の減少 |
| `TEST_DISABLED` | error | `pytest.mark.skip/skipif/xfail`、`pytest.skip/xfail()`、JS/TS の `it/test/describe.skip/only/todo`、`xit/xtest/xdescribe` の追加 |
| `ASSERTION_DECREASED` | error | テストファイル単位のアサーション数の減少 |
| `EMPTY_ASSERTION` | error | `assert True`、`assert 1`、`expect(true)` の追加 |
| `COVERAGE_LOWERED` | error | `--cov-fail-under`、`--fail-under`、`fail_under`、`coverageThreshold` 内の数値閾値の引き下げ |
| `SUPPRESSION_ADDED` | warning | `# noqa`、`# type: ignore`、`eslint-disable`、`@ts-ignore`、`@ts-expect-error` の追加 |
| `SNAPSHOT_UPDATED` | warning | `.snap` / `.snapshot` の変更・追加・削除。期待値更新の妥当性を人間が確認 |

Python は `.py`、JS/TS は `.js/.jsx/.ts/.tsx/.mjs/.cjs` に対応します。`test_` で始まる名前、`_test` で終わる stem、`.test.` / `.spec.` を含む名前、`tests/` / `test/` / `__tests__/` 内のファイルをテストとして扱います。言語別のケース検出式は `rules.py` の `TEST_PATTERNS` に集約しています。

行番号は原則として変更後、削除・件数減少は変更前です。件数減少は最初の該当行を根拠として表示します。

## criteria の書き方

TOML の `[[criteria]]` に条件を列挙します。`id`（一意）、`description`、`kind` が必須で、`severity` は `error`（既定）または `warning` です。

```toml
[[criteria]]
id = "readme"
description = "README が存在する"
kind = "file_exists"
path = "README.md"

[[criteria]]
id = "usage"
description = "使用例がある"
kind = "file_contains"
path = "README.md"
pattern = "acv check"

[[criteria]]
id = "source"
description = "実装を変更する"
kind = "diff_touches"
pattern = "src/*"

[[criteria]]
id = "license"
description = "ライセンスを維持する"
kind = "diff_not_touches"
pattern = "LICENSE"

[[criteria]]
id = "tests"
description = "実装変更にテストを伴う"
kind = "test_added_for"
path = "src/*"

[[criteria]]
id = "syntax"
description = "構文を確認する"
kind = "command"
command = ["python", "-m", "compileall", "-q", "src"]
timeout = 30
```

完全な例は [examples/criteria.toml](examples/criteria.toml) にあります。

- `file_exists` / `file_contains`: 比較先のファイルを確認。`file_contains` は Python の正規表現（MULTILINE）です。
- `diff_touches` / `diff_not_touches`: 追加・削除を含む変更パスが glob に一致するかを確認します。Python の `fnmatchcase` を用いるため、`*` は `/` にも一致します。`**` に特別な意味はありません。
- `test_added_for`: `path` の glob に一致する変更があれば、削除以外のテストファイルの追加・変更が1件以上必要です。対象変更がなければ合格です。実装とテストの意味的な対応関係は判定しません。
- `command`: 文字列配列をシェルを介さず実行し、終了コード 0 を要求します。`timeout` は正の有限秒数で既定30秒です。出力末尾4000文字までを結果に含めます。

command は比較先のファイル内容をリポジトリ内の `.acv-command-*` にコピーし、そのルートで実行します。`--head` 指定時も指定コミットの内容を使います。Git 管理情報、無視された `.venv` / `node_modules`、ファイルの実行ビットはコピーしません。環境変数と PATH は継承します。必要なツールは呼び出し環境に用意し、スクリプトは `['sh', 'scripts/check.sh']` のようにインタープリター経由で実行してください。一時コピーは終了時に削除します。

**command 実行はサンドボックスではありません。** ホストへの書き込みやネットワークアクセスも可能なため、信頼できる条件・コードだけに `--run-commands` を付けてください。ツール自体の検査・テストは有料 API キーも外部サービスも必要としません。

## デモ

```sh
uv sync
./scripts/demo.sh
```

このリポジトリ内の `.tmp/` に一時 Git リポジトリを作り、fixture 用のコミットを1回作成します。作業ブランチの commit / reset / checkout は行いません。良い変更の合格と悪い変更の不合格を検証し、デモ自体は成功時に 0 で終了します。

実行出力（Python 3.12 / macOS）:

```text
=== 良い変更 ===
判定: 合格（変更 3 ファイル）
[条件:合格] ready README に完了と記載されている
  根拠: 対象: README.md / 正規表現: 完了
[条件:合格] tests 実装変更にテスト変更を伴う
  根拠: 対象変更: あり / テスト追加・変更: あり
[条件:合格] syntax Python の構文を検証する
  根拠: 終了コード 0
終了コード: 0
=== 悪い変更 ===
判定: 不合格（変更 4 ファイル）
[error] COVERAGE_LOWERED coverage.toml:1 カバレッジ閾値が引き下げられました。
  根拠: fail_under = 20
[error] TEST_DISABLED tests/test_new.py:2 テストの無効化・実行限定が追加されました。
  根拠: @pytest.mark.skip(reason='保留')
[error] EMPTY_ASSERTION tests/test_new.py:4 空のアサーションが追加されました。
  根拠: assert True
[error] TEST_FILE_DELETED tests/test_old.py:1 テストファイルが削除されました。
  根拠: 削除前のファイル全体
[error] TEST_COUNT_DECREASED tests/test_old.py:1 テストケース数が減少しました。
  根拠: 1 → 0（削除前の行番号）
[error] ASSERTION_DECREASED tests/test_old.py:2 アサーション数が減少しました。
  根拠: 1 → 0（削除前の行番号）
[条件:不合格] ready README に完了と記載されている
  根拠: 対象: README.md / 正規表現: 完了
[条件:合格] tests 実装変更にテスト変更を伴う
  根拠: 対象変更: あり / テスト追加・変更: あり
[条件:合格] syntax Python の構文を検証する
  根拠: 終了コード 0
終了コード: 1
```

## エージェントのワークフローへの組み込み

1. 変更前に人間が criteria を用意し、信頼できる比較元の ref を記録します。
2. Codex / Claude Code 等に実装を依頼します。
3. 次の検査を実行し、検出箇所と条件一覧を人間がレビューします。

```sh
acv check --base origin/main --criteria examples/criteria.toml --run-commands --fail-on warning
```

エージェントが criteria 自体を弱めていないことも確認してください。外部の信頼できる criteria を `--criteria` に指定する運用も可能です。

## 開発・品質チェック

```sh
uv sync
./scripts/check.sh
```

`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy --strict src`、`uv run pytest` を順に実行します。pytest は一時 Git リポジトリを用い、外部ネットワークに接続せず、カバレッジ 85% 以上を要求します。依存の初回取得にはネットワークが必要です。キャッシュと一時ファイルはこのリポジトリ内に置きます。GitHub Actions は含めません。

## 制限

- ヒューリスティックなので誤検知・見逃しがあります。コメント・文字列中のパターンにも反応し、エイリアス、動的生成、複数行表現、パラメーター化による実行件数は完全には追跡しません。
- テストの移動・改名は Git の rename 検出（`git diff -M`、既定の類似度 50%）で追跡し、移動前の内容と比べて検査します。出力の `renamed_files`（テキストでは「移動:」）に対応を示します。テストとして検出されないパスへの移動は削除として扱います。類似度が 50% 未満の書き換え（別のテストフレームワークへの移行など）は削除と追加として扱うため、削除の検出結果は人間が確認してください。作業ツリーとの比較では、未追跡ファイルを含めるために `.git` 内の一時インデックスを使います（本来のインデックスと作業ツリーは変更しません）。
- アサーションはファイル単位の字句的な件数です。意味の弱い期待値への変更や、同数の別テストへの置換までは保証しません。
- 閾値の対応付けはキーと出現順です。設定の移動・複雑な式や閾値設定そのものの削除は検出できない場合があります。
- スナップショット更新は内容の正しさを検証せず、該当拡張子の差分を一律警告します。
- 作業ツリーの無視ファイル、シンボリックリンク、サブモジュール内は対象外です。コミット内のリンクはリンク先文字列を通常のファイル内容として読み、一時コピーでもリンクとして復元しません。
- 比較対象の全ファイルをメモリに読みます。巨大なリポジトリ向けの最適化や、バイナリ専用の解析はありません。
- command のプロセスグループをタイムアウト時に停止しますが、独立して起動したプロセスなどを完全には制御できません。Windows の command 実行は未対応です。

ライセンス: [MIT](LICENSE)
