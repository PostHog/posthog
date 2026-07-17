"""One-shot eval for AI subscription report generation.

Each case runs the real report pipeline (`generate_ai_report`) once against the shared read-only
Hedgebox demo team and scores what came back:

- `query_coverage` — the fraction of planned HogQL steps that actually executed. This is the headline
  signal the whole pipeline exists to protect: a subscription whose generated queries fail delivers a
  broken report. It's also what regressed in the incident these prompt changes came from.
- `no_window_now_leak` — the generated HogQL must filter the analysis window with the `{{date_range}}`
  placeholder, never `now()`. Guards the one real clash from sharing the SQL-assistant reference docs
  (whose examples use `now()`), so a doc example can't pull the planner off the placeholder contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asgiref.sync import sync_to_async

from posthog.models import Team, User

from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import generate_ai_report
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import compute_report_window
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

SUITE_KIND = SuiteKind.ONE_SHOT

# 30-day window matches a typical monthly subscription and comfortably spans the demo data range.
_WINDOW_DAYS = 30


class QueryCoverage(Scorer):
    """Fraction of planned HogQL steps that executed successfully — the headline pipeline metric."""

    def _name(self) -> str:
        return "query_coverage"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if not output or output.get("total_steps") is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        total = output["total_steps"]
        if total == 0:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Planner produced no steps"})
        coverage = (total - output["failed_steps"]) / total
        return Score(
            name=self._name(),
            score=coverage,
            metadata={
                "total_steps": total,
                "failed_steps": output["failed_steps"],
                "error_types": output.get("error_types", []),
            },
        )


class NoWindowNowLeak(Scorer):
    """The window must be filtered with the placeholder, never `now()` — 0.0 if any query uses `now(`."""

    def _name(self) -> str:
        return "no_window_now_leak"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        hogqls = (output or {}).get("hogqls")
        if not hogqls:
            return Score(name=self._name(), score=None, metadata={"reason": "No generated HogQL"})
        offenders = [q for q in hogqls if "now(" in q.lower()]
        return Score(
            name=self._name(),
            score=0.0 if offenders else 1.0,
            metadata={"offending_queries": offenders},
        )


async def _run_report(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
    assert task_ctx.demo_data is not None, "one-shot suite requires demo data"
    team_id = task_ctx.demo_data.master_team_id

    @sync_to_async
    def _load() -> tuple[Team, User]:
        team = Team.objects.get(id=team_id)
        user = User.objects.filter(organization_memberships__organization=team.organization).first()
        assert user is not None, "demo team has no user"
        return team, user

    team, user = await _load()
    window = compute_report_window(team, last_scheduled_cutoff=None, now=datetime.now(UTC), window_days=_WINDOW_DAYS)

    try:
        result = await generate_ai_report(team=team, user=user, prompt=case.prompt, window=window)
    except Exception as exc:
        # A pipeline failure is a 0-coverage result, not an infra error — it's exactly what we score.
        return {"total_steps": 0, "failed_steps": 0, "hogqls": [], "error_types": [type(exc).__name__], "raised": True}

    diagnostics = result.diagnostics
    return {
        "total_steps": len(diagnostics),
        "failed_steps": sum(1 for d in diagnostics if not d.ok),
        "hogqls": [d.hogql for d in diagnostics],
        "error_types": [d.error_type for d in diagnostics if not d.ok],
        "last_message": result.markdown[:500],
    }


async def eval_ai_subscription_hogql(ctx: EvalContext) -> None:
    await OneShotPrivateEval(
        experiment_name="ai-subscription-hogql",
        cases=[
            BaseEvalCase(
                name="signups_and_uploads_trend",
                prompt="Weekly summary of new signups and file uploads, with a day-by-day trend for each.",
            ),
            BaseEvalCase(
                name="engagement_vs_previous_period",
                prompt="How is overall user engagement trending compared to the previous period?",
            ),
            BaseEvalCase(
                name="most_and_least_active_events",
                prompt="What are the most active and least active events by volume this period?",
            ),
            BaseEvalCase(
                # Exercises first-ever-per-user + a person-property breakdown — the join/window path the
                # relaxed constraints are meant to support.
                name="first_time_uploaders_by_plan",
                prompt="Users whose first ever file upload happened this period, broken down by their plan.",
            ),
        ],
        scorers=[QueryCoverage(), NoWindowNowLeak()],
        task=_run_report,
        ctx=ctx,
    )
