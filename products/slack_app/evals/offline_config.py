from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, dict[str, OfflineScorer]] = {
    "followup_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557c-9b63-776a-91f3-113ab57c025a")),
        "followup_routing": OfflineScorer(kind="boolean", version=UUID("01a1557c-d1ca-7c68-96eb-5406fd8dde02")),
        "no_unasked_wake": OfflineScorer(kind="boolean", version=UUID("01a1557c-dd52-78d0-a1f1-1854076c09ac")),
    },
    "model_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557c-e620-710d-82d2-de63990000f1")),
        "model_override_match": OfflineScorer(kind="boolean", version=UUID("01a1557c-ee78-7412-9b90-2ecf80591aa0")),
        "no_unasked_override": OfflineScorer(kind="boolean", version=UUID("01a1557c-fd45-7a93-8852-b64bcf13eeb8")),
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
    "reply_suggestions": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557d-49a7-7417-aa9f-4dbe00ec7b47")),
        "no_unasked_buttons": OfflineScorer(kind="boolean", version=UUID("01a1557d-5b16-755e-ab88-b824e5103a97")),
        "reply_offer": OfflineScorer(kind="boolean", version=UUID("01a1557d-5266-7853-a431-6213cfba1b5a")),
        "suggested_replies_fit": OfflineScorer(kind="boolean", version=UUID("01a1557d-bcc0-7a96-8d22-4d6e91998d5d")),
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
