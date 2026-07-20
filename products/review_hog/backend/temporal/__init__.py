from products.review_hog.backend.temporal.activities import (
    append_code_review_artefact_activity,
    build_body_activity,
    dedup_activity,
    fail_status_comment_activity,
    fetch_pr_data_activity,
    finalize_status_comment_activity,
    generate_schemas_activity,
    load_blind_spots_skill_activity,
    load_perspectives_activity,
    load_validation_skill_activity,
    post_status_comment_activity,
    publish_review_activity,
    resolve_acting_user_activity,
    review_chunk_activity,
    select_perspectives_activity,
    split_chunks_activity,
    sync_review_skills_activity,
    validate_chunk_activity,
    validate_github_integration_activity,
)
from products.review_hog.backend.temporal.resolution import ResolvePRWorkflow, resolve_threads_activity
from products.review_hog.backend.temporal.workflow import (
    ReviewPerspectivesWorkflow,
    ReviewPRWorkflow,
    ValidateIssuesWorkflow,
)

WORKFLOWS = [
    ReviewPRWorkflow,
    ReviewPerspectivesWorkflow,
    ValidateIssuesWorkflow,
    ResolvePRWorkflow,
]

ACTIVITIES = [
    validate_github_integration_activity,
    fetch_pr_data_activity,
    resolve_acting_user_activity,
    sync_review_skills_activity,
    generate_schemas_activity,
    split_chunks_activity,
    load_perspectives_activity,
    select_perspectives_activity,
    load_blind_spots_skill_activity,
    review_chunk_activity,
    dedup_activity,
    load_validation_skill_activity,
    validate_chunk_activity,
    build_body_activity,
    publish_review_activity,
    post_status_comment_activity,
    finalize_status_comment_activity,
    fail_status_comment_activity,
    append_code_review_artefact_activity,
    resolve_threads_activity,
]
