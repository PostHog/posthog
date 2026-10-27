from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a178ac-ded9-7c35-a805-7fa5d89181c3")),
    "answer_mentions": OfflineScorer(kind="numeric", version=UUID("01a178ac-a3e7-767b-845b-e0cd688962b7")),
    "call_budget": OfflineScorer(kind="numeric", version=UUID("01a178ac-d4d6-7f42-b31b-efa4546672ff")),
}


def offline_suite(key: str, *, metrics: Sequence[str]) -> OfflineEvalSuite:
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in ("exit_code_zero", *metrics)},
        tags=("team:apm", "component:logs"),
    )
