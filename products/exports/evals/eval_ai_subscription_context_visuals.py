import asyncio
from typing import Any, cast

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
        generated = wanted.get("generated_chart")
        passed = output.get("context_visual_refs") == wanted.get("context_visual_refs") and (
            generated is None or output.get("generated_chart") is generated
        )
        return Score(name=self._name(), score=int(passed), metadata={"actual": output})


_CANDIDATE = ContextVisualCandidate(
    ref=CONTEXT_REF,
    insight_id=701,
    title="Daily signups",
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
_CASE_DATA: tuple[tuple[str, str, list[str], bool | None], ...] = (
    ("directly_useful_saved_visual", "Summarize 30-day signups.", [CONTEXT_REF], None),
    ("saved_visual_has_wrong_range", "Chart 7-day signups.", [], True),
    ("linked_visual_is_irrelevant", "Chart 30-day paid_bill revenue.", [], True),
    ("saved_visual_replaces_generated_duplicate", "Chart 30-day signups.", [CONTEXT_REF], False),
)
CASES = [
    BaseEvalCase(
        name=name,
        prompt=prompt,
        expected={SCORE_KEY: {"context_visual_refs": refs, "generated_chart": generated}},
    )
    for name, prompt, refs, generated in _CASE_DATA
]


async def eval_ai_subscription_context_visuals(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        def generate() -> dict[str, Any]:
            assert task_ctx.demo_data is not None
            team = Team.objects.get(id=task_ctx.demo_data.master_team_id)
            user = cast(
                User,
                User.objects.filter(organization_memberships__organization_id=team.organization_id).first(),
            )
            plan = generate_query_plan(
                cleaned_prompt=case.prompt,
                context_blob="Known events: signed_up, paid_bill.",
                formatted_context="The saved insight computed 42 signups.",
                context_visual_candidates=(_CANDIDATE,),
                team=team,
                user=user,
            )
            return {
                "context_visual_refs": plan.context_visual_refs,
                "generated_chart": any(step.chart for step in plan.steps),
            }

        return await asyncio.to_thread(generate)

    await OneShotPrivateEval(
        experiment_name="ai-subscription-context-visual-selection",
        cases=CASES,
        scorers=[ContextVisualSelection()],
        task=task,
        ctx=ctx,
    )
