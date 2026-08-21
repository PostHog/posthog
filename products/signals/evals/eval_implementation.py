from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.signals.eval.agentic.braintrust import (
    ImplementationFixJudge,
    decode_implementation,
    deterministic_scorers,
)
from products.signals.eval.agentic.cases.implementation import CASES
from products.signals.eval.agentic.runners import run_implementation
from products.signals.eval.agentic.scorers_implementation import default_implementation_scorers
from products.signals.eval.agentic.suite import run_suite

SUITE_KIND = SuiteKind.SANDBOXED


async def eval_implementation(ctx: EvalContext) -> None:
    await run_suite(
        experiment_name="signals-implementation",
        cases=CASES,
        prompt=lambda case: case.issue_prompt,
        runner=run_implementation,
        scorers=[
            *deterministic_scorers(default_implementation_scorers(), CASES, decode_implementation),
            ImplementationFixJudge(CASES),
        ],
        ctx=ctx,
    )
