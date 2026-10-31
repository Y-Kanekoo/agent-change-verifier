"""検出パターンと差分に限定した検出の検証。"""

import pytest

from agent_change_verifier.repository import Change
from agent_change_verifier.rules import inspect, is_test


@pytest.mark.parametrize(
    "path",
    [
        "test_app.py",
        "app_test.py",
        "tests/app.ts",
        "app.test.js",
        "app.spec.tsx",
        "__tests__/app.jsx",
    ],
)
def test_test_paths(path: str) -> None:
    assert is_test(path)


@pytest.mark.parametrize(
    "line",
    [
        "@pytest.mark.skip(reason='理由')",
        "@pytest.mark.skipif(True)",
        "@pytest.mark.xfail",
        "pytest.skip('理由')",
        "pytest.xfail('理由')",
        "it.skip('例', () => {})",
        "describe.skip('例', () => {})",
        "xit('例', () => {})",
        "test.only('例', () => {})",
        "test.todo('例')",
        "xdescribe('例', () => {})",
        "xtest('例', () => {})",
    ],
)
def test_disabled(line: str) -> None:
    result = inspect([Change("tests/app.ts", "", line, False)])
    assert any(f.rule_id == "TEST_DISABLED" for f in result)


@pytest.mark.parametrize(
    "line",
    ["# noqa", "# type: ignore", "// eslint-disable", "// @ts-ignore", "// @ts-expect-error"],
)
def test_suppressions(line: str) -> None:
    assert inspect([Change("app.py", "", line, False)])[0].rule_id == "SUPPRESSION_ADDED"


@pytest.mark.parametrize("line", ["assert True", "assert 1 # 仮", "expect(true).toBe(true)"])
def test_empty_assertions(line: str) -> None:
    assert inspect([Change("tests/test_app.py", "", line, False)])[0].rule_id == "EMPTY_ASSERTION"


@pytest.mark.parametrize(
    "template",
    [
        "--cov-fail-under={}",
        "--cov-fail-under {}",
        "--fail-under={}",
        "fail_under = {}",
        "coverageThreshold: {{ global: {{ statements: {}, branches: 80 }} }}",
        '"coverageThreshold": {{"global": {{"lines": {}}}}}',
    ],
)
def test_coverage_reduction(template: str) -> None:
    result = inspect([Change("config", template.format(90), template.format(85), False)])
    assert result[0].rule_id == "COVERAGE_LOWERED"
    assert not inspect([Change("config", template.format(85), template.format(90), False)])


def test_unchanged_lines_and_reductions() -> None:
    before = "@pytest.mark.skip\ndef test_one():\n    assert 1 == 1\nasync def test_two():\n    assert 2 == 2\n"
    after = "@pytest.mark.skip\ndef test_one():\n    assert 1 == 1\n"
    results = inspect([Change("test_app.py", before, after, False)])
    assert {result.rule_id for result in results} == {"TEST_COUNT_DECREASED", "ASSERTION_DECREASED"}
    assert not inspect([Change("app.py", "lines: 90", "lines: 80", False)])


def test_javascript_counts() -> None:
    results = inspect(
        [
            Change(
                "app.test.ts",
                "it('a', () => expect(1))\ntest('b', () => expect(2))",
                "it('a', () => expect(1))",
                False,
            )
        ]
    )
    assert {r.rule_id for r in results} == {"TEST_COUNT_DECREASED", "ASSERTION_DECREASED"}
