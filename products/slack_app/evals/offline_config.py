from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, dict[str, OfflineScorer]] = {
    "feature_tip_picker": {
        "feature_tip": OfflineScorer(kind="boolean", version=UUID("01a1692e-3104-7138-a33c-ab37d915ac6e")),
        "no_forced_tip": OfflineScorer(kind="boolean", version=UUID("01a1692e-3589-7893-a06a-e0f1893d8a19")),
    },
    "followup_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557c-9b63-776a-91f3-113ab57c025a")),
        "followup_routing": OfflineScorer(kind="boolean", version=UUID("01a1557c-d1ca-7c68-96eb-5406fd8dde02")),
        "no_unasked_wake": OfflineScorer(kind="boolean", version=UUID("01a1557c-dd52-78d0-a1f1-1854076c09ac")),
    },
    "interview_sentiment": {
        "interview_sentiment": OfflineScorer(kind="boolean", version=UUID("01a1783a-9ee4-73a5-bbdf-fe91e943eb96")),
        "no_unasked_invite": OfflineScorer(kind="boolean", version=UUID("01a1783a-9ee4-73a5-bbdf-fe92235d3e9c")),
    },
    "model_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557c-e620-710d-82d2-de63990000f1")),
        "model_override_match": OfflineScorer(kind="boolean", version=UUID("01a1557c-ee78-7412-9b90-2ecf80591aa0")),
        "no_unasked_override": OfflineScorer(kind="boolean", version=UUID("01a1557c-fd45-7a93-8852-b64bcf13eeb8")),
    },
    "needs_repo": {
        "needs_repo": OfflineScorer(kind="boolean", version=UUID("01a1cb12-ad4f-7cb7-ab46-c1ed42db9cc7")),
    },
    "posthog_first": {
        "docs_searched": OfflineScorer(kind="boolean", version=UUID("01a1557d-0f40-7999-9f55-d969442fe434")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557d-0682-75c3-bb88-5a620ba6ce5d")),
        "no_third_party_recommendation": OfflineScorer(
            kind="boolean", version=UUID("01a1557d-2542-7805-a791-6c3ac5f875b2")
        ),
        "posthog_product_answer": OfflineScorer(kind="boolean", version=UUID("01a1557d-1aa6-7fb4-ae3b-2fab4be4c44e")),
    },
    "project_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557d-2ef4-7ee8-9f53-ae73633d593d")),
        "no_unasked_project_switch": OfflineScorer(
            kind="boolean", version=UUID("01a1557d-415e-78ff-8bcb-1e6cc67b77ac")
        ),
        "project_route_match": OfflineScorer(kind="boolean", version=UUID("01a1557d-37df-756c-a5fb-73edde0b1561")),
    },
    "repo_selection_routing": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1a29b-30cf-7fef-907b-69efc56159bb")),
        "routing_stage_correct": OfflineScorer(kind="boolean", version=UUID("01a1a29b-32a3-7dfc-b5b7-33931ddc73ac")),
        "routing_repository_correct": OfflineScorer(
            kind="boolean", version=UUID("01a1a29b-3447-794a-afcb-83778635c273")
        ),
    },
    "untagged_question": {
        "untagged_question": OfflineScorer(kind="boolean", version=UUID("01a15a43-79f8-76bd-98ad-aaacc69b7059")),
        "no_unasked_answer": OfflineScorer(kind="boolean", version=UUID("01a15a43-8605-78ef-acf6-cc940d3876ab")),
    },
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    domain = key.split("/", 1)[1].split("::", 1)[0].removeprefix("eval_")
    scorers = _SCORERS[domain]
    component = domain.replace("_", "-")
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: scorers[metric] for metric in enrolled_metrics},
        tags=("team:surfaces", f"component:slack-app/{component}"),
    )
