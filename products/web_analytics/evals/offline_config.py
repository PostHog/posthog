from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a21d57-24c3-7310-9b8b-62ae4677b08c")),
    "first_relevant_tool": OfflineScorer(kind="boolean", version=UUID("01a21d57-24c3-7310-9b8b-62af8137611a")),
    "web_answer_correctness": OfflineScorer(kind="numeric", version=UUID("01a21d57-24c3-7310-9b8b-62b0a282dd86")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:analytics", "component:web-analytics"),
    )
