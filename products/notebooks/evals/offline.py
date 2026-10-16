from uuid import UUID

from posthoganalytics.ai.evaluations import ScorerKind

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite

_COMMON_KINDS: dict[str, ScorerKind] = {
    "exit_code_zero": "boolean",
    "required_tool_call": "boolean",
    "notebook_created": "boolean",
    "cell_runs_completed": "boolean",
}
_COMMON_VERSIONS = {
    "exit_code_zero": UUID("01a143b7-3a45-7c94-9e46-4cf75ab3ee12"),
    "required_tool_call": UUID("01a143b7-78c5-78c4-9f0d-60e0f5965b1a"),
    "notebook_created": UUID("01a143b7-7b0e-7834-ab39-e6d37d772ff7"),
    "cell_runs_completed": UUID("01a143b7-7d19-7d4a-8fc8-3d06a32da5ef"),
}

NOTEBOOK_CELLS = OfflineEvalSuite(
    key="notebooks/eval_notebook_cells::eval_notebook_cells",
    project_id=2,
    scorer_kinds={**_COMMON_KINDS, "notebook_run_completed": "boolean"},
    scorer_versions={
        **_COMMON_VERSIONS,
        "notebook_run_completed": UUID("01a143b7-7ec4-77b5-9a32-7e9984aa2755"),
    },
)

NOTEBOOK_ANALYSIS = OfflineEvalSuite(
    key="notebooks/eval_notebook_analysis::eval_notebook_analysis",
    project_id=2,
    scorer_kinds={**_COMMON_KINDS, "churn_cohort_surfaced": "numeric", "notebook_approach_quality": "numeric"},
    scorer_versions={
        **_COMMON_VERSIONS,
        "churn_cohort_surfaced": UUID("01a143b7-830b-77b4-82f5-89f8d83f4ab7"),
        "notebook_approach_quality": UUID("01a143b7-850d-72c8-85d9-0d74005d8f37"),
    },
)
