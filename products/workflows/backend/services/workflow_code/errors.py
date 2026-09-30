from enum import StrEnum

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import WorkflowCodeErrorStatus

DocumentPath = tuple[str | int, ...]


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
