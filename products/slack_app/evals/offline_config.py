from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, dict[str, OfflineScorer]] = {
    "daily_summary": {
        "daily_summary_rank": OfflineScorer(kind="boolean", version=UUID("01a20812-34f2-7b87-8f71-e1526d57a727")),
        "summary_covers": OfflineScorer(kind="numeric", version=UUID("01a20813-2f71-7465-a149-77450d2f39d4")),
        "summary_omits_chatter": OfflineScorer(kind="boolean", version=UUID("01a20813-364e-7d6d-aded-84da2591cca0")),
        "summary_voice": OfflineScorer(kind="boolean", version=UUID("01a20813-3c72-7d26-b6cd-2b63347abeb0")),
        "summary_faithful": OfflineScorer(kind="boolean", version=UUID("01a20813-4297-7757-825e-9e94f065393a")),
        "summary_intro_fits": OfflineScorer(kind="boolean", version=UUID("01a20ccb-1417-74de-a2de-c4f0e2e99a2d")),
        "summary_not_clipped": OfflineScorer(kind="boolean", version=UUID("01a20ccb-1a2e-7ebe-98ce-f2f1f20c896c")),
    },
    "feature_tip_picker": {
        "feature_tip": OfflineScorer(kind="boolean", version=UUID("01a1692e-3104-7138-a33c-ab37d915ac6e")),
        "no_forced_tip": OfflineScorer(kind="boolean", version=UUID("01a1692e-3589-7893-a06a-e0f1893d8a19")),
    },
    "followup_classifier": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557c-9b63-776a-91f3-113ab57c025a")),
        "followup_routing": OfflineScorer(kind="boolean", version=UUID("01a1557c-d1ca-7c68-96eb-5406fd8dde02")),
        "no_unasked_wake": OfflineScorer(kind="boolean", version=UUID("01a1557c-dd52-78d0-a1f1-1854076c09ac")),
    },
    "message_sentiment": {
        "message_sentiment": OfflineScorer(kind="boolean", version=UUID("01a2091d-1c56-7629-8b6a-d250303e4101")),
        "happy_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-33f8-7924-9d9f-96eeed5131b6")),
        "neutral_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-3a54-7d05-896a-d44e0c05da64")),
        "confused_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-4133-7a6c-82fb-8eb9749ca846")),
        "not_happy_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-47c7-7b59-963e-6fb3c63b8c92")),
        "frustrated_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-4eee-72d7-a522-bc895ccbb508")),
        "unhappy_detected": OfflineScorer(kind="boolean", version=UUID("01a2091d-2010-7932-927d-d6265b1f5ac7")),
        "no_unasked_reaction": OfflineScorer(kind="boolean", version=UUID("01a2091d-26bf-73fe-b957-cb178c844481")),
        "no_unasked_gif": OfflineScorer(kind="boolean", version=UUID("01a2091d-2d54-7f16-8a58-cee8d6f96b1f")),
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
    "work_focus_handoff": {
        "work_focus_keep": OfflineScorer(kind="boolean", version=UUID("01a20813-492d-7df6-9c54-2f4c7dbdf902")),
        "no_handed_off_offer": OfflineScorer(kind="boolean", version=UUID("01a20813-4f01-7376-81b1-4933692bfb90")),
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
