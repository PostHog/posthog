from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.signals.backend.temporal.types import render_signals_to_text
from products.signals.evals.agentic.braintrust import (
    RepositorySelectionJudge,
    decode_repo_selection,
    deterministic_scorers,
)
from products.signals.evals.agentic.cases.repo_selection import CASES
from products.signals.evals.agentic.runners import run_repo_selection
from products.signals.evals.agentic.scorers_repo_selection import default_repo_selection_scorers
from products.signals.evals.agentic.seeders import seed_repository_catalog
from products.signals.evals.agentic.suite import run_suite

SUITE_KIND = SuiteKind.SANDBOXED


async def eval_repository_selection(ctx: EvalContext) -> None:
    await run_suite(
        experiment_name="signals-repository-selection",
        cases=CASES,
        prompt=lambda case: (
            case.context or render_signals_to_text([signal.to_signal_data() for signal in case.signals])
        ),
        runner=run_repo_selection,
        scorers=[
            *deterministic_scorers(default_repo_selection_scorers(), CASES, decode_repo_selection),
            RepositorySelectionJudge(CASES),
        ],
        setup=seed_repository_catalog,
        ctx=ctx,
    )
