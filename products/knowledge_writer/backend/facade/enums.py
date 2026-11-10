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
