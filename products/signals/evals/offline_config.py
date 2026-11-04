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
