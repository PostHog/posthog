from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "baseline_acceptable_owner": OfflineScorer(kind="boolean", version=UUID("05de0b17-950f-4f3b-99f8-87da2c9a4d3f")),
    "proposed_acceptable_owner": OfflineScorer(kind="boolean", version=UUID("14b13312-e13f-4137-a536-f06575cbc837")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:self-driving", "component:signals"),
    )
