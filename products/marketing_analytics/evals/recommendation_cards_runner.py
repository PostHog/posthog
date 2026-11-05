"""Sequential evaluation of the production card generator with synthetic discovery inputs.

Run with ``python -m products.marketing_analytics.evals.recommendation_cards_runner``.
The default dry run replaces HTTP responses and proves wiring only. ``--live`` uses
the production Go gateway configuration and can incur charges. Discovery, access
checks, persistence, and Celery are outside this evaluation.
"""

from __future__ import annotations

import os
import sys
import json
import socket
import hashlib
import argparse
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4, uuid5

from unittest.mock import patch

import httpx
from anthropic.resources.messages import Messages
from anthropic.types import Message
from pydantic import BaseModel

from products.marketing_analytics.evals.recommendation_card_cases import (
    RecommendationCardCase,
    recommendation_card_cases,
)
from products.marketing_analytics.evals.report_writer import write_report_checkpoint

if TYPE_CHECKING:
    from products.marketing_analytics.backend.services.conversion_recommendations import ConversionRecommendationResults


class CardTrial(TypedDict, total=False):
    trial_id: str
    case: str
    trial_index: int
    expected: list[dict[str, object]]
    catalog: list[dict[str, object]]
    configured_goals: list[dict[str, object]]
    request_model: str
    request_max_tokens: int
    request_sha256: str
    response_model: str
    stop_reason: str | None
    usage: dict[str, object]
    response: dict[str, object]
    results: ConversionRecommendationResults
    failures: list[str]
    status: str
    error_type: str
    http_status: int | None


class CardEvaluationReport(TypedDict):
    run_id: str
    mode: str
    status: str
    planned_trials: int
    completed_trials: int
    contract_passed: bool | None
    semantic_review_status: str
    coverage: str
    excluded: list[str]
    source_sha256: dict[str, str]
    prompt_sha256: str
    trials: list[CardTrial]
    error_type: str | None
    error_stage: str | None


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bootstrap() -> None:
    import django  # noqa: PLC0415 — CLI bootstrap must precede importing production models
    from django.conf import settings  # noqa: PLC0415 — CLI bootstrap must precede importing production models

    os.environ["TEST"] = "1"
    os.environ["OPT_OUT_CAPTURE"] = "1"
    os.environ["SELF_CAPTURE"] = "0"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    with patch.object(socket.socket, "connect", side_effect=RuntimeError("Network is disabled during eval startup")):
        settings.DATABASES = {alias: {"ENGINE": "django.db.backends.dummy"} for alias in settings.DATABASES}
        settings.CACHES = {
            alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"} for alias in settings.CACHES
        }
        django.setup()


def _contract_failures(case: RecommendationCardCase, results: ConversionRecommendationResults) -> list[str]:
    expected = {item.source_ref: item for item in case.expected}
    actual = {item.source_ref: item for item in results.recommendations}
    candidates = {item["source_ref"]: item for item in case.candidates}
    failures = []
    if set(actual) != set(expected):
        failures.append("Recommended sources differ from the expected business outcomes")
    if len(actual) != len(results.recommendations):
        failures.append("Duplicate sources survived recommendation generation")
    for source_ref, recommendation in actual.items():
        spec = expected.get(source_ref)
        if spec is None:
            continue
        if recommendation.intent != spec.intent:
            failures.append(f"{source_ref}: incorrect intent")
        if recommendation.amount_property != spec.amount_property:
            failures.append(f"{source_ref}: incorrect amount mapping")
        candidate = recommendation.candidate
        original = candidates[source_ref]
        if candidate.kind != original["kind"]:
            failures.append(f"{source_ref}: source kind changed")
        if candidate.kind == "ActionsNode" and candidate.action_id != original.get("action_id"):
            failures.append(f"{source_ref}: action identity lost")
        if candidate.kind == "EventsNode" and candidate.event != original.get("event"):
            failures.append(f"{source_ref}: event identity lost")
        if spec.intent in ("revenue", "customer") and not recommendation.questions:
            failures.append(f"{source_ref}: missing business questions")
    return failures


def _dry_response(case: RecommendationCardCase) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_synthetic_dry_run",
            "type": "message",
            "role": "assistant",
            "model": "synthetic-transport-response",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_synthetic",
                    "name": "recommendations",
                    "input": {
                        "recommendations": [
                            {
                                "source_ref": item.source_ref,
                                "name": case.name,
                                "reason": "Synthetic transport fixture.",
                                "intent": item.intent,
                                "amount_property": item.amount_property,
                                "questions": (
                                    ["Confirm the amount units and currency."]
                                    if item.intent == "revenue"
                                    else ["Confirm how the action identifies a first customer."]
                                    if item.intent == "customer"
                                    else []
                                ),
                            }
                            for item in case.expected
                        ],
                    },
                }
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )


def run_card_evaluation(
    cases: Sequence[RecommendationCardCase],
    *,
    trials: int = 1,
    dry_run: bool = True,
    checkpoint: Callable[[CardEvaluationReport], None] | None = None,
) -> CardEvaluationReport:
    from django.db.backends.base.base import (
        BaseDatabaseWrapper,  # noqa: PLC0415 — production models require initialized Django
    )
    from django.test import override_settings  # noqa: PLC0415 — production models require initialized Django

    from posthog.llm.gateway_client import (
        resolve_ai_gateway_config,  # noqa: PLC0415 — production models require initialized Django
    )
    from posthog.models import Team, User  # noqa: PLC0415 — production models require initialized Django

    from products.marketing_analytics.backend.models.conversion_setup import (  # noqa: PLC0415 — production models require initialized Django
        ConversionRecommendationRun,
    )
    from products.marketing_analytics.backend.services import (  # noqa: PLC0415 — production models require initialized Django
        conversion_recommendations as production,
    )

    if not cases or not 1 <= trials <= 5:
        raise ValueError("Select at least one case and between one and five trials")
    run_id = uuid4()
    report: CardEvaluationReport = {
        "run_id": str(run_id),
        "mode": "dry_run" if dry_run else "live",
        "status": "running",
        "planned_trials": len(cases) * trials,
        "completed_trials": 0,
        "contract_passed": None,
        "semantic_review_status": "not_applicable" if dry_run else "pending",
        "coverage": "Production generate/suggest, Go gateway client, tool schema/parser, and source validation",
        "excluded": [
            "discovery queries",
            "permissions and AI consent",
            "persistence",
            "Celery",
            "semantic prose grading",
        ],
        "source_sha256": {
            "service": _digest(Path(production.__file__).read_bytes()),
            "runner": _digest(Path(__file__).read_bytes()),
            "cases": _digest(Path(__file__).with_name("recommendation_card_cases.py").read_bytes()),
            "report_writer": _digest(Path(__file__).with_name("report_writer.py").read_bytes()),
        },
        "prompt_sha256": _digest(production.RECOMMENDATION_PROMPT.encode()),
        "trials": [],
        "error_type": None,
        "error_stage": None,
    }
    records = report["trials"]
    original_create = cast(Callable[..., Message], Messages.create)
    current: CardTrial = {}
    stage = "gateway_configuration"

    def save_checkpoint() -> None:
        if checkpoint is not None:
            checkpoint(report)

    save_checkpoint()

    def record_create(*args: object, **kwargs: object) -> Message:
        current["request_model"] = str(kwargs["model"])
        current["request_max_tokens"] = cast(int, kwargs["max_tokens"])
        current["request_sha256"] = _digest(json.dumps(kwargs, sort_keys=True).encode())
        response = original_create(*args, **kwargs)
        current["response_model"] = response.model
        current["stop_reason"] = response.stop_reason
        current["usage"] = response.usage.model_dump(mode="json")
        current["response"] = response.model_dump(mode="json")
        if response.stop_reason != "tool_use":
            raise ValueError("Incomplete recommendation generation")
        return response

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                BaseDatabaseWrapper,
                "ensure_connection",
                side_effect=RuntimeError("Database access is excluded from this evaluation"),
            )
        )
        stack.enter_context(patch.object(Messages, "create", autospec=True, side_effect=record_create))
        if dry_run:
            stack.enter_context(
                override_settings(
                    AI_GATEWAY_URL="http://gateway.invalid/v1", AI_GATEWAY_API_KEY="synthetic-dry-run-key"
                )
            )
            stack.enter_context(
                patch.object(socket.socket, "connect", side_effect=RuntimeError("Network is disabled in dry runs"))
            )
        try:
            if resolve_ai_gateway_config() is None:
                raise ValueError("Go gateway is not configured")
            stage = "candidate_validation"
            prepared = [
                (case, [production.ConversionCandidate.model_validate(item) for item in case.candidates])
                for case in cases
            ]
            now = datetime(2026, 1, 31, tzinfo=UTC)
            team = Team(id=-1)
            user = User(id=-1, distinct_id="synthetic-recommendation-card-eval", email="card-eval@example.com")
            service = production.ConversionRecommendationService(team, user)
            stack.enter_context(patch.object(service, "require_generation_access", return_value=None))
            stack.enter_context(patch.object(production, "is_privacy_mode_enabled", return_value=True))
            for case, candidates in prepared:
                for trial in range(trials):
                    trial_id = uuid5(run_id, f"{case.name}/{trial}")
                    current = {
                        "trial_id": str(trial_id),
                        "case": case.name,
                        "trial_index": trial,
                        "expected": [asdict(item) for item in case.expected],
                        "catalog": [candidate.model_dump(mode="json") for candidate in candidates],
                        "configured_goals": list(case.configured_goals),
                        "status": "running",
                    }
                    records.append(current)
                    save_checkpoint()
                    run = ConversionRecommendationRun(
                        id=trial_id,
                        team=team,
                        requested_by=user,
                        lookback_days=30,
                        date_from=now - timedelta(days=30),
                        date_to=now,
                    )
                    with ExitStack() as case_stack:
                        stage = "generation"
                        case_stack.enter_context(patch.object(service, "candidates", return_value=candidates))
                        case_stack.enter_context(
                            patch.object(
                                service,
                                "configured_goals",
                                return_value=[
                                    production.ConfiguredConversionGoal.model_validate(goal)
                                    for goal in case.configured_goals
                                ],
                            )
                        )
                        if dry_run:
                            case_stack.enter_context(
                                patch.object(httpx.HTTPTransport, "handle_request", return_value=_dry_response(case))
                            )
                        results = service.generate(run)
                    stage = "contract_gate"
                    failures = _contract_failures(case, results)
                    current["results"] = results
                    current["failures"] = failures
                    current["status"] = "failed" if failures else "passed"
                    report["completed_trials"] = len(records)
                    save_checkpoint()
        except (Exception, KeyboardInterrupt) as error:
            status = "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
            if current.get("status") not in ("passed", "failed"):
                current["status"] = status
            current["error_type"] = type(error).__name__
            current["http_status"] = cast(int | None, getattr(error, "status_code", None))
            report["status"] = status
            report["error_type"] = type(error).__name__
            report["error_stage"] = stage
            save_checkpoint()
            return report
    passed = all(record["status"] == "passed" for record in records)
    report["status"] = "dry_run_passed" if dry_run and passed else "contract_passed" if passed else "failed"
    report["contract_passed"] = passed if not dry_run else None
    save_checkpoint()
    return report


def _serialize(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Use the configured Go gateway; incurs provider charges")
    mode.add_argument("--dry-run", action="store_true", help="Use synthetic HTTP responses (default); no quality claim")
    parser.add_argument("--case", action="append", default=[], help="Exact case name; repeat to select multiple cases")
    parser.add_argument("--trials", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--output", type=Path, help="Write JSON to a new file; refuses to overwrite")
    args = parser.parse_args(argv)
    cases = recommendation_card_cases()
    unknown = set(args.case) - {case.name for case in cases}
    if unknown:
        parser.error(f"Unknown cases: {', '.join(sorted(unknown))}")
    selected = tuple(case for case in cases if not args.case or case.name in args.case)
    if args.output is not None:
        with args.output.open("x"):
            pass

    def checkpoint(report: CardEvaluationReport) -> None:
        if args.output is not None:
            write_report_checkpoint(args.output, json.dumps(report, indent=2, default=_serialize) + "\n")

    _bootstrap()
    report = run_card_evaluation(selected, trials=args.trials, dry_run=not args.live, checkpoint=checkpoint)
    if args.output is None:
        sys.stdout.write(json.dumps(report, indent=2, default=_serialize) + "\n")
    return 0 if report["status"] in ("contract_passed", "dry_run_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
