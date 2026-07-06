"""Load generated case datasets (committed JSON) into typed Case objects with scorers.

Generation (DB-backed) is separate from loading (pure, no DB) so the large suite runs anywhere.
Regenerate the JSON with ``python manage.py generate_eval_cases``.

Loading is resilient: a malformed row (or file) is skipped with a warning naming the file and
row index rather than aborting the whole suite, and rows whose content duplicates an earlier
one are dropped with a logged count (duplicates pseudo-replicate one scenario in the pass rate).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from products.signals.eval.agentic.datasets import (
    EvalCase,
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

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(__file__).parent / "generated"
# Data-grounded/generated research runs against a small, fast-cloning repo (verdict rests on data).
_FAST_REPO = "posthog/posthog-python"

C = TypeVar("C", bound=EvalCase)


def _read(step: str) -> list[dict]:
    path = GENERATED_DIR / f"{step}.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("generated dataset %s is not valid JSON (%s); skipping the file", path, exc)
        return []
    if not isinstance(rows, list):
        logger.warning("generated dataset %s is not a JSON array; skipping the file", path)
        return []
    return rows


def _load_rows(step: str, parse: Callable[[dict], tuple[str, C]]) -> list[C]:
    """Parse each row into (content_key, case); skip malformed rows and duplicate content."""
    out: list[C] = []
    seen: set[str] = set()
    duplicates = 0
    for i, d in enumerate(_read(step)):
        case_id = d.get("case_id", "?") if isinstance(d, dict) else "?"
        try:
            key, case = parse(d)
        except Exception as exc:
            logger.warning("skipping malformed generated case %s.json[%d] (case_id=%s): %s", step, i, case_id, exc)
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        out.append(case)
    if duplicates:
        logger.warning(
            "dropped %d duplicate-content %s cases at load (regenerate to fix the dataset)", duplicates, step
        )
    return out


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


def _content_key(*parts: Any) -> str:
    return json.dumps(parts, sort_keys=True, default=str)


def load_generated_research() -> list[ResearchCase]:
    def parse(d: dict) -> tuple[str, ResearchCase]:
        e = d.get("expectation", {})
        exp = ResearchExpectation(
            expected_actionability=tuple(e["expected_actionability"]) if "expected_actionability" in e else None,
            expected_priority=tuple(e["expected_priority"]) if "expected_priority" in e else None,
            expect_data_evidence=bool(e.get("expect_data_evidence", False)),
            summary_must_mention=tuple(e.get("summary_must_mention", ())),
        )
        case = ResearchCase(
            case_id=d["case_id"],
            step="research",
            repo=_FAST_REPO,
            signals=(_signal(d["signal"]),),
            expected=exp,
            scorers=(*default_research_scorers(), ResearchSummaryJudge()),
        )
        return _content_key(d["signal"]["content"], e), case

    return _load_rows("research", parse)


def load_generated_repo_selection() -> list[RepoSelectionCase]:
    def parse(d: dict) -> tuple[str, RepoSelectionCase]:
        if d.get("expect_null"):
            exp = RepoSelectionExpectation(expect_null=True)
        else:
            raw = d["expected_repository"]
            exp = RepoSelectionExpectation(expected_repository=tuple(raw) if isinstance(raw, list) else raw)
        case = RepoSelectionCase(
            case_id=d["case_id"],
            step="repo_selection",
            signals=(_signal(d["signal"]),),
            expected=exp,
            scorers=default_repo_selection_scorers(),
        )
        return _content_key(d["signal"]["content"], d.get("expected_repository"), d.get("expect_null")), case

    return _load_rows("repo_selection", parse)


def load_generated_implementation() -> list[ImplementationCase]:
    def parse(d: dict) -> tuple[str, ImplementationCase]:
        e = d.get("expectation", {})
        exp = ImplementationExpectation(
            expected_file_substrings=_to_tuple(e.get("expected_file_substrings")),
            forbidden_file_substrings=_to_tuple(e.get("forbidden_file_substrings")),
            expected_diff_keywords=_to_tuple(e.get("expected_diff_keywords")),
            min_files_changed=int(e.get("min_files_changed", 1)),
            max_files_changed=e.get("max_files_changed"),
        )
        case = ImplementationCase(
            case_id=d["case_id"],
            step="implementation",
            repo=d["repo"],
            issue_prompt=d["issue_prompt"],
            expected=exp,
            scorers=(*default_implementation_scorers(), ImplementationFixJudge()),
        )
        return _content_key(d["repo"], d["issue_prompt"], e), case

    return _load_rows("implementation", parse)


def load_generated(step: str) -> list:
    return {
        "research": load_generated_research,
        "repo_selection": load_generated_repo_selection,
        "implementation": load_generated_implementation,
    }[step]()
