"""検査結果の共通形式。"""

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning"]
Status = Literal["passed", "failed", "not_run"]


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    file: str
    line: int
    message: str
    evidence: str


@dataclass(frozen=True)
class CriterionResult:
    id: str
    description: str
    kind: str
    status: Status
    evidence: str
    severity: Severity = "error"
