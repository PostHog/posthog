from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncWindow(Generic[T]):
    """Inclusive sync window bounds resolved by a connector before fetching data."""

    start: T
    end: T
