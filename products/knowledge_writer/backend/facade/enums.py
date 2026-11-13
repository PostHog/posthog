from enum import StrEnum


class DocsRequestSource(StrEnum):
    REPO_MERGE = "repo_merge"
    COMMAND_TAG = "command_tag"


class DocsChangeKind(StrEnum):
    UPDATE = "update"
    CREATE = "create"
    REMOVE = "remove"
    REVIEW_EXISTING = "review_existing_docs"


class CriterionEffect(StrEnum):
    BLOCKS = "blocks"
    SUPPORTS = "supports"
    NEUTRAL = "neutral"


class MergeCheckFailure(StrEnum):
    ADMISSION_LOOKUP_FAILED = "admission_lookup_failed"
    NO_PULL_REQUEST_NUMBER = "no_pull_request_number"
    NO_DOCS_GITHUB = "no_docs_github"
    JUDGE_CLIENT_UNAVAILABLE = "judge_client_unavailable"
    RETRIES_EXHAUSTED = "retries_exhausted"
