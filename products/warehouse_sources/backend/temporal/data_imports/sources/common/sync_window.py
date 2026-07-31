from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncWindow(Generic[T]):
    """Start/end bounds of one connector sync window; inclusivity of each bound is defined by the connector."""

    start: T
    end: T
