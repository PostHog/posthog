from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

FIRST_REPORT_SUITE = OfflineEvalSuite.from_scorers(
    key="signals/eval_first_report::eval_first_report",
    project_id=2,
    tags=("team:self-driving", "component:signals/first-report"),
    scorers={
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1634a-9ee8-7933-80b1-9669b21a3923")),
        "scout_outcome": OfflineScorer(kind="boolean", version=UUID("01a1634a-a2e5-7558-a408-0f22a9c70188")),
        "grounded_closeout": OfflineScorer(kind="boolean", version=UUID("01a1634a-a675-72d2-bbe4-e763f4090b55")),
        "report_quality": OfflineScorer(kind="boolean", version=UUID("01a1634a-aa66-791c-9b68-c19993e118e7")),
        "qualified_report_within_5_minutes": OfflineScorer(
            kind="boolean", version=UUID("01a1634a-ae28-7775-87ba-662aa3b699d2")
        ),
        "planted_issue_recall": OfflineScorer(kind="boolean", version=UUID("01a1634a-b1e9-7f04-9d7b-33e025fd9e69")),
    },
)

SELF_DRIVING_ACTIVATION_SUITE = OfflineEvalSuite.from_scorers(
    key="signals/eval_self_driving_activation::eval_self_driving_activation",
    project_id=2,
    tags=("team:self-driving", "component:signals/self-driving-activation"),
    scorers={
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9ca607e2aed1")),
        "activation_notice_delivered": OfflineScorer(
            kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9ca776d6cba6")
        ),
        "self_driving_mentioned": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9ca864bcc84f")),
        "self_driving_suggested": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9ca91b1e18d2")),
        "activation_link_present": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9caabc0b0000")),
        "answered_question_first": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9cabfcef2eba")),
        "no_unprompted_suggestion": OfflineScorer(kind="boolean", version=UUID("01a218cf-403f-7630-85a0-9cac562b78fb")),
    },
)
