from typing import Generic, TypeVar

from posthog.dataclasses import frozen

T = TypeVar("T")


@frozen
class SyncWindow(Generic[T]):
    """Start/end bounds of one connector sync window; inclusivity of each bound is defined by the connector."""

    start: T
    end: T
