"""CLI の不正引数も日本語で説明する。"""

import pytest

from agent_change_verifier.cli import main


def test_invalid_arguments_are_japanese(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["check"])
    assert error.value.code == 2
    assert "引数エラー" in capsys.readouterr().err
