from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.signals.evals.agentic.braintrust import ScoutDecisionQualityJudge, decode_scout, deterministic_scorers
from products.signals.evals.agentic.cases.scout import CASES
from products.signals.evals.agentic.runners import run_scout
from products.signals.evals.agentic.scorers_scout import default_scout_scorers
from products.signals.evals.agentic.seeders import seed_scout_project
from products.signals.evals.agentic.suite import run_suite

SUITE_KIND = SuiteKind.SANDBOXED


async def eval_scout(ctx: EvalContext) -> None:
    await run_suite(
        experiment_name="signals-scout",
        cases=CASES,
        prompt=lambda case: f"Canonical scout run: {case.skill_name}",
        runner=run_scout,
        scorers=[
            *deterministic_scorers(default_scout_scorers(), CASES, decode_scout),
            ScoutDecisionQualityJudge(CASES),
        ],
        setup=seed_scout_project,
        ctx=ctx,
    )
