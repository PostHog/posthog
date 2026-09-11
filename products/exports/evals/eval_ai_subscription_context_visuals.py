from __future__ import annotations

import asyncio
from typing import Any

from posthog.schema import InsightVizNode

from posthog.models import Team, User

from products.exports.backend.temporal.subscriptions.ai_subscription.report_context import ContextVisualCandidate
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import generate_query_plan
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

SUITE_KIND = SuiteKind.ONE_SHOT
SCORE_KEY = "context_visual_selection"
CONTEXT_REF = "insight:701"


class ContextVisualSelection(Scorer):
    def _name(self) -> str:
        return SCORE_KEY

    def _run_eval_sync(
        self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None, **kwargs: Any
    ) -> Score:
        wanted = (expected or {}).get(SCORE_KEY, {})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0, metadata={"reason": (output or {}).get("error", "no output")})
        actual_refs = output.get("context_visual_refs")
        refs_match = actual_refs == wanted.get("context_visual_refs")
        generated = wanted.get("generated_chart")
        generated_match = generated is None or output.get("generated_chart") is generated
        return Score(name=self._name(), score=1 if refs_match and generated_match else 0, metadata={"actual": output})


def _candidate(title: str) -> ContextVisualCandidate:
    return ContextVisualCandidate(
        ref=CONTEXT_REF,
        insight_id=701,
        title=title,
        visualization=InsightVizNode.model_validate(
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "signed_up"}],
                    "dateRange": {"date_from": "-30d"},
                },
            }
        ),
    )


def _case(name: str, prompt: str, title: str, refs: list[str], generated: bool | None = None) -> BaseEvalCase:
    expected: dict[str, Any] = {"context_visual_refs": refs}
    if generated is not None:
        expected["generated_chart"] = generated
    return BaseEvalCase(
        name=name,
        prompt=prompt,
        metadata={"title": title},
        expected={SCORE_KEY: expected},
    )


CASES = [
    _case(
        "directly_useful_saved_visual",
        "Summarize signups over the last 30 days.",
        "Daily signups — last 30 days",
        [CONTEXT_REF],
    ),
    _case(
        "saved_visual_has_wrong_range",
        "Chart daily signups for the last 7 days.",
        "Daily signups — prior 30 days",
        [],
        True,
    ),
    _case(
        "linked_visual_is_irrelevant",
        "Chart daily revenue from paid_bill over the last 30 days.",
        "Daily signups",
        [],
        True,
    ),
    _case(
        "saved_visual_replaces_generated_duplicate",
        "Show weekly signups for the last 8 weeks as a chart.",
        "Weekly signups — last 8 weeks",
        [CONTEXT_REF],
        False,
    ),
]


async def eval_ai_subscription_context_visuals(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        def generate() -> dict[str, Any]:
            if task_ctx.demo_data is None:
                raise RuntimeError("One-shot demo data is unavailable")
            team = Team.objects.get(id=task_ctx.demo_data.master_team_id)
            user = User.objects.filter(organization_memberships__organization_id=team.organization_id).first()
            if user is None:
                raise RuntimeError("Demo user is unavailable")
            candidate = _candidate(str(case.metadata["title"]))
            plan = generate_query_plan(
                cleaned_prompt=case.prompt,
                context_blob="Known events: signed_up, paid_bill. Use the report window requested by the user.",
                formatted_context=f"Computed results for {case.metadata['title']}.",
                context_visual_candidates=(candidate,),
                team=team,
                user=user,
            )
            return {
                "context_visual_refs": plan.context_visual_refs,
                "generated_chart": any(step.chart is not None for step in plan.steps),
                "last_message": plan.overall_intent,
            }

        return await asyncio.to_thread(generate)

    await OneShotPrivateEval(
        experiment_name="ai-subscription-context-visual-selection",
        cases=CASES,
        scorers=[ContextVisualSelection()],
        task=task,
        ctx=ctx,
    )
