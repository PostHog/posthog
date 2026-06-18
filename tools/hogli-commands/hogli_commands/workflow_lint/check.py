"""Check ABC and result type for workflow lint rules.

Mirrors the shape of `hogli_commands.product.checks.ProductCheck` so the two
frameworks can be unified later (rule of three) without rewriting either.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .model import Workflow


@dataclass(slots=True)
class Issue:
    """One actionable problem reported by a check."""

    workflow: str  # workflow filename, e.g. "ci-backend.yml"
    message: str
    file: str | None = None  # path used for GitHub annotations; defaults to the workflow path
    job: str | None = None
    step: str | None = None

    def render(self) -> str:
        parts: list[str] = [self.workflow]
        if self.job is not None:
            parts.append(f"job '{self.job}'")
        if self.step is not None:
            parts.append(self.step)
        return f"{': '.join(parts)}: {self.message}"


@dataclass(slots=True)
class CheckResult:
    issues: list[Issue] = field(default_factory=list)


class WorkflowCheck(ABC):
    """A single workflow lint rule.

    Subclasses set the three class attrs and implement :meth:`run`.

    - ``id``: stable, machine-friendly identifier (used by ``--check`` filter).
    - ``label``: short human-readable name shown in CLI output and GH annotations.
    - ``description``: one-line summary; shown by ``--list``.
    """

    id: str
    label: str
    description: str

    @abstractmethod
    def run(self, workflows: list[Workflow]) -> CheckResult: ...

    @property
    def fix_hint(self) -> str | None:
        """Optional remediation message printed once at the end if any issue fires."""
        return None


__all__ = ["CheckResult", "Issue", "WorkflowCheck"]
