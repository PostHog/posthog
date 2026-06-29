from products.review_hog.backend.temporal.activities import (
    analyze_chunk_activity,
    build_body_activity,
    combine_and_clean_activity,
    dedup_activity,
    fetch_pr_data_activity,
    generate_schemas_activity,
    load_perspectives_activity,
    load_validation_skill_activity,
    publish_review_activity,
    resolve_acting_user_activity,
    review_chunk_activity,
    split_chunks_activity,
    sync_review_skills_activity,
    validate_github_integration_activity,
    validate_issue_activity,
)
from products.review_hog.backend.temporal.workflow import (
    AnalyzeChunksWorkflow,
    ReviewPerspectivesWorkflow,
    ReviewPRWorkflow,
    ValidateIssuesWorkflow,
)

WORKFLOWS = [
    ReviewPRWorkflow,
    AnalyzeChunksWorkflow,
    ReviewPerspectivesWorkflow,
    ValidateIssuesWorkflow,
]

ACTIVITIES = [
    validate_github_integration_activity,
    fetch_pr_data_activity,
    resolve_acting_user_activity,
    sync_review_skills_activity,
    generate_schemas_activity,
    split_chunks_activity,
    load_perspectives_activity,
    analyze_chunk_activity,
    review_chunk_activity,
    combine_and_clean_activity,
    dedup_activity,
    load_validation_skill_activity,
    validate_issue_activity,
    build_body_activity,
    publish_review_activity,
]
