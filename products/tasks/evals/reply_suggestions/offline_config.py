from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

REPLY_SUGGESTIONS_SUITE = OfflineEvalSuite.from_scorers(
    key="tasks/eval_reply_suggestions::eval_reply_suggestions",
    project_id=2,
    tags=("team:agent-infrastructure", "component:tasks/reply-suggestions"),
    scorers={
        "no_unasked_buttons": OfflineScorer(kind="boolean", version=UUID("01a1557d-5b16-755e-ab88-b824e5103a97")),
        "reply_offer": OfflineScorer(kind="boolean", version=UUID("01a1557d-5266-7853-a431-6213cfba1b5a")),
        "suggested_replies_fit": OfflineScorer(kind="boolean", version=UUID("01a1557d-bcc0-7a96-8d22-4d6e91998d5d")),
    },
)
