from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "cell_runs_completed": OfflineScorer(kind="boolean", version=UUID("01a143b7-7d19-7d4a-8fc8-3d06a32da5ef")),
    "churn_cohort_surfaced": OfflineScorer(kind="numeric", version=UUID("01a143b7-830b-77b4-82f5-89f8d83f4ab7")),
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a143b7-3a45-7c94-9e46-4cf75ab3ee12")),
    "notebook_approach_quality": OfflineScorer(kind="numeric", version=UUID("01a143b7-850d-72c8-85d9-0d74005d8f37")),
    "notebook_created": OfflineScorer(kind="boolean", version=UUID("01a143b7-7b0e-7834-ab39-e6d37d772ff7")),
    "notebook_run_completed": OfflineScorer(kind="boolean", version=UUID("01a143b7-7ec4-77b5-9a32-7e9984aa2755")),
    "required_tool_call": OfflineScorer(kind="boolean", version=UUID("01a143b7-78c5-78c4-9f0d-60e0f5965b1a")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:data-tools", "component:notebooks"),
    )
