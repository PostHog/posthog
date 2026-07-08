import pytest

from posthog.schema import DataWarehouseSourceCategory

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_every_source_has_a_valid_category(source_type):
    category = ALL_SOURCES[source_type].get_source_config.category
    assert category is not None, (
        f"{source_type} is missing a category. Set "
        f"category=DataWarehouseSourceCategory.<X> in its get_source_config — "
        f"see the implementing-warehouse-sources skill."
    )
    assert isinstance(category, DataWarehouseSourceCategory)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_source_keywords_are_a_list_of_strings(source_type):
    keywords = ALL_SOURCES[source_type].get_source_config.keywords
    if keywords is None:
        return
    assert isinstance(keywords, list)
    assert all(isinstance(keyword, str) and keyword == keyword.lower() for keyword in keywords)
