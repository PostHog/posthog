from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.signals.eval.agentic.braintrust import ScoutDecisionQualityJudge, decode_scout, deterministic_scorers
from products.signals.eval.agentic.cases.scout import CASES
from products.signals.eval.agentic.runners import run_scout
from products.signals.eval.agentic.scorers_scout import default_scout_scorers
from products.signals.eval.agentic.suite import run_suite

SUITE_KIND = SuiteKind.SANDBOXED


async def eval_scout(ctx: EvalContext) -> None:
    await run_suite(
        experiment_name="signals-scout",
        cases=CASES,
        prompt=lambda case: case.observations,
        runner=run_scout,
        scorers=[
            *deterministic_scorers(default_scout_scorers(), CASES, decode_scout),
            ScoutDecisionQualityJudge(CASES),
        ],
        ctx=ctx,
    )
