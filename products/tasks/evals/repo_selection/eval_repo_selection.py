"""Selector quality: given one request and the same candidate evidence, does the discovery agent
pick the right repository or abstain?

Every case runs the production `select_repository` against the synthetic catalog in
`fixtures`. The needs-repo classifier and the cascade do not run here, so
classifier behavior cannot hide a difference between selector models; the end-to-end path is
`slack_app/eval_repo_selection_routing`.

Compare models with one harness comparison, for example:

    hogli evals tasks/eval_repo_selection --trials 3 --max-sandboxes 4 \\
        --compare-model claude:claude-haiku-5-5 \\
        --compare-model codex:gpt-6-luna,reasoning_effort=medium \\
        --compare-model codex:gpt-6-luna,reasoning_effort=medium,service_tier=flex
"""

from __future__ import annotations

from posthog.egress.limiter.policies import Priority

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade import api as tasks_facade

from .fixtures import FIXTURE_VERSION, SELECTOR_CASES, fixture_fingerprint
from .offline_config import REPO_SELECTION_SUITE
from .runner import selector_case_runner
from .scorers import SELECTOR_SCORERS, selector_expected
from .seeders import scenario_seeder

EXPERIMENT_NAME = "repo-selection-selector"


async def eval_repo_selection(ctx: EvalContext) -> None:
    await SandboxedEval(
        offline_suite=REPO_SELECTION_SUITE,
        send_to_posthog=True,
        experiment_name=EXPERIMENT_NAME,
        cases=[
            SandboxedEvalCase(
                name=case.scenario.name,
                # Shown in local logs only; the selector receives the rendered thread from the runner.
                prompt=case.scenario.context_block,
                setup=scenario_seeder(case.scenario),
                expected=selector_expected(case.expected),
                metadata={
                    "category": case.category,
                    "fixture_version": FIXTURE_VERSION,
                    "fixture_fingerprint": fixture_fingerprint(),
                },
                # The selector reads only the seeded repository cache, never project data.
                inherit_demo_data=False,
            )
            for case in SELECTOR_CASES
        ],
        scorers=[scorer() for scorer in SELECTOR_SCORERS],
        # Self-Driving's selection path: the Signals origin attributes the run to
        # `signals_repo_selection`, and report generation runs at batch priority.
        case_runner=selector_case_runner(
            {case.scenario.name: case.scenario for case in SELECTOR_CASES},
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            priority=Priority.BATCH,
        ),
        ctx=ctx,
    )
