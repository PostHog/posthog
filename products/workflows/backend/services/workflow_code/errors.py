from collections.abc import Callable
from enum import StrEnum

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import WorkflowCodeErrorStatus

DocumentPath = tuple[str | int, ...]

MAX_REPORTED_ERRORS = 50
_MAX_SHOWN_VALUE_LENGTH = 60


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
    """The errors in a file. `left_out` counts further errors found but not described."""

    def __init__(self, errors: list[DocumentError], left_out: int = 0) -> None:
        super().__init__(f"{len(errors) + left_out} document error(s)")
        self.errors = errors
        self.left_out = left_out


class ErrorCollector:
    """Describes the first MAX_REPORTED_ERRORS errors and counts the rest.

    Describing an error formats its path, so a file with a mistake in every value would otherwise cost
    memory in proportion to its values times their depth.
    """

    def __init__(self) -> None:
        self.errors: list[DocumentError] = []
        self.left_out = 0

    def add(self, describe: Callable[[], DocumentError]) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(describe())
        else:
            self.left_out += 1


def shortened(value: str) -> str:
    if len(value) <= _MAX_SHOWN_VALUE_LENGTH:
        return value
    return f"{value[:_MAX_SHOWN_VALUE_LENGTH]}..."


def shown(value: str) -> str:
    """A value quoted back in an error, cut short so a long value does not fill the response."""
    return f"'{shortened(value)}'"


def format_path(path: DocumentPath | None) -> str | None:
    if path is None:
        return None
    formatted = ""
    for part in path:
        if isinstance(part, int):
            formatted += f"[{part}]"
        else:
            formatted += f".{shortened(part)}" if formatted else shortened(part)
    return formatted


def describe_path(path: DocumentPath | None) -> str:
    return format_path(path) or "The file"
