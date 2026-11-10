from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

REPO_SELECTION_SUITE = OfflineEvalSuite.from_scorers(
    key="tasks/eval_repo_selection::eval_repo_selection",
    project_id=2,
    tags=("team:self-driving", "component:tasks/repo-selection"),
    scorers={
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1a29b-2872-7fa1-9657-362160748643")),
        "repo_selection_correct": OfflineScorer(kind="boolean", version=UUID("01a1a29b-2b7c-780a-844c-0d6554836396")),
        "correct_abstention": OfflineScorer(kind="boolean", version=UUID("01a1a29b-2d22-7be2-969a-cd8d145c6287")),
        "selector_completed": OfflineScorer(kind="boolean", version=UUID("01a1a29b-2ee1-788f-ae8b-0081c4a997b0")),
    },
)
