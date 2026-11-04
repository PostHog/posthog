from enum import StrEnum


class DocsRequestSource(StrEnum):
    REPO_MERGE = "repo_merge"
    COMMAND_TAG = "command_tag"


class DocsChangeKind(StrEnum):
    UPDATE = "update"
    CREATE = "create"
    REMOVE = "remove"
