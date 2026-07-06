"""Load generated case datasets (committed JSON) into typed Case objects with scorers.

Generation (DB-backed) is separate from loading (pure, no DB) so the large suite runs anywhere.
Regenerate the JSON with ``python manage.py generate_eval_cases``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from products.signals.eval.agentic.datasets import (
    ImplementationCase,
    ImplementationExpectation,
    RepoSelectionCase,
    RepoSelectionExpectation,
    ResearchCase,
    ResearchExpectation,
    SignalSpec,
)
from products.signals.eval.agentic.scorers_implementation import default_implementation_scorers
from products.signals.eval.agentic.scorers_judge import ImplementationFixJudge, ResearchSummaryJudge
from products.signals.eval.agentic.scorers_repo_selection import default_repo_selection_scorers
from products.signals.eval.agentic.scorers_research import default_research_scorers

GENERATED_DIR = Path(__file__).parent / "generated"
# Data-grounded/generated research runs against a small, fast-cloning repo (verdict rests on data).
_FAST_REPO = "posthog/posthog-python"


def _read(step: str) -> list[dict]:
    path = GENERATED_DIR / f"{step}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _signal(d: dict) -> SignalSpec:
    return SignalSpec(
        content=d["content"],
        signal_id=d.get("signal_id", "sig_gen"),
        source_product=d.get("source_product", "error_tracking"),
        source_type=d.get("source_type", "issue_created"),
        source_id=d.get("source_id", d.get("signal_id", "gen")),
    )


def _to_tuple(v: Any) -> tuple:
    if v is None:
        return ()
    return tuple(v) if isinstance(v, (list, tuple)) else (v,)


def load_generated_research() -> list[ResearchCase]:
    out: list[ResearchCase] = []
    for d in _read("research"):
        e = d.get("expectation", {})
        exp = ResearchExpectation(
            expected_actionability=tuple(e["expected_actionability"]) if "expected_actionability" in e else None,
            expected_priority=tuple(e["expected_priority"]) if "expected_priority" in e else None,
            expect_data_evidence=bool(e.get("expect_data_evidence", False)),
            summary_must_mention=tuple(e.get("summary_must_mention", ())),
        )
        out.append(
            ResearchCase(
                case_id=d["case_id"],
                step="research",
                repo=_FAST_REPO,
                signals=(_signal(d["signal"]),),
                expected=exp,
                scorers=(*default_research_scorers(), ResearchSummaryJudge()),
            )
        )
    return out


def load_generated_repo_selection() -> list[RepoSelectionCase]:
    out: list[RepoSelectionCase] = []
    for d in _read("repo_selection"):
        if d.get("expect_null"):
            exp = RepoSelectionExpectation(expect_null=True)
        else:
            raw = d["expected_repository"]
            exp = RepoSelectionExpectation(expected_repository=tuple(raw) if isinstance(raw, list) else raw)
        out.append(
            RepoSelectionCase(
                case_id=d["case_id"],
                step="repo_selection",
                signals=(_signal(d["signal"]),),
                expected=exp,
                scorers=default_repo_selection_scorers(),
            )
        )
    return out


def load_generated_implementation() -> list[ImplementationCase]:
    out: list[ImplementationCase] = []
    for d in _read("implementation"):
        e = d.get("expectation", {})
        exp = ImplementationExpectation(
            expected_file_substrings=_to_tuple(e.get("expected_file_substrings")),
            forbidden_file_substrings=_to_tuple(e.get("forbidden_file_substrings")),
            expected_diff_keywords=_to_tuple(e.get("expected_diff_keywords")),
            min_files_changed=int(e.get("min_files_changed", 1)),
            max_files_changed=e.get("max_files_changed"),
        )
        out.append(
            ImplementationCase(
                case_id=d["case_id"],
                step="implementation",
                repo=d["repo"],
                issue_prompt=d["issue_prompt"],
                expected=exp,
                scorers=(*default_implementation_scorers(), ImplementationFixJudge()),
            )
        )
    return out


def load_generated(step: str) -> list:
    return {
        "research": load_generated_research,
        "repo_selection": load_generated_repo_selection,
        "implementation": load_generated_implementation,
    }[step]()
