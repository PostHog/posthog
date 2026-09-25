from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.signals.evals.agentic.braintrust import ResearchSummaryJudge, decode_research, deterministic_scorers
from products.signals.evals.agentic.cases.research import CASES
from products.signals.evals.agentic.runners import run_research
from products.signals.evals.agentic.scorers_research import default_research_scorers
from products.signals.evals.agentic.seeders import seed_research_project
from products.signals.evals.agentic.suite import run_suite

SUITE_KIND = SuiteKind.SANDBOXED


async def eval_research(ctx: EvalContext) -> None:
    await run_suite(
        experiment_name="signals-research",
        cases=CASES,
        prompt=lambda case: "\n\n".join(signal.content for signal in case.signals),
        runner=run_research,
        scorers=[
            *deterministic_scorers(default_research_scorers(), CASES, decode_research),
            ResearchSummaryJudge(CASES),
        ],
        setup=seed_research_project,
        ctx=ctx,
    )
