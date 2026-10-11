from collections.abc import Iterable
from typing import Any

from sources.sdk import SourceResponse


def sync_items(source: SourceResponse) -> Iterable[Any]:
    items = source.items()
    assert isinstance(items, Iterable)
    return items
