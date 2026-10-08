from collections.abc import Iterable
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


def sync_items(source: SourceResponse) -> Iterable[Any]:
    items = source.items()
    assert isinstance(items, Iterable)
    return items
