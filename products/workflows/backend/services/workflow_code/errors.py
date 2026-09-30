from enum import StrEnum

from django.db import models

from posthog.dataclasses import frozen

DocumentPath = tuple[str | int, ...]


class WorkflowCodeErrorStatus(models.TextChoices):
    INVALID_YAML = "invalid_yaml"
    YAML_FEATURE_NOT_ALLOWED = "yaml_feature_not_allowed"
    DUPLICATE_KEY = "duplicate_key"
    CONTENT_TOO_LARGE = "content_too_large"
    UNSUPPORTED_VERSION = "unsupported_version"
    MISSING_FIELD = "missing_field"
    UNKNOWN_FIELD = "unknown_field"
    INVALID_VALUE = "invalid_value"
    UNKNOWN_TYPE = "unknown_type"
    DUPLICATE_STEP_ID = "duplicate_step_id"
    SECRET_INPUT = "secret_input"
    UNKNOWN_TEMPLATE = "unknown_template"
    INVALID_WORKFLOW = "invalid_workflow"
    STATUS_CHANGE_NOT_ALLOWED = "status_change_not_allowed"
    CONFLICT = "conflict"


class PointsAt(StrEnum):
    VALUE = "value"
    KEY = "key"
    PARENT = "parent"


@frozen
class Position:
    line: int
    column: int


@frozen
class DocumentError:
    status: WorkflowCodeErrorStatus
    message: str
    why: str
    fix: str
    path: DocumentPath | None
    points_at: PointsAt = PointsAt.VALUE
    position: Position | None = None


class DocumentInvalid(Exception):
    def __init__(self, errors: list[DocumentError]) -> None:
        super().__init__(f"{len(errors)} document error(s)")
        self.errors = errors


def format_path(path: DocumentPath | None) -> str | None:
    if path is None:
        return None
    formatted = ""
    for part in path:
        if isinstance(part, int):
            formatted += f"[{part}]"
        else:
            formatted += f".{part}" if formatted else part
    return formatted


def describe_path(path: DocumentPath | None) -> str:
    return format_path(path) or "The file"
