"""Source capability checks used by external schema APIs."""

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def source_supports_column_selection(source_type: str) -> bool:
    """Column selection is available for every registered source: SQL sources project the
    selection into their SELECT, everything else is projected generically just before the
    Delta write. Unknown source types stay False so the UI fails closed.

    Excludes managed-schema sources (Stripe, Paddle, Zendesk): their HogQL tables expose a
    fixed canonical schema, so dropping a referenced column breaks the query."""
    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception as e:
        capture_exception(e)
        return False
    return not source.has_managed_hogql_schema


def source_supports_row_filters(source_type: str) -> bool:
    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception as e:
        capture_exception(e)
        return False
    # `bool()` guards against test mocks whose attribute access returns a Mock — orjson can't serialize.
    return bool(source.supports_row_filters)


def source_requires_exact_column_metadata(source_type: str) -> bool:
    """Whether enabled column names are interpolated into a source-side query.

    These sources require exact source identifiers. Warehouse table columns have already
    passed through dlt normalization, so they are not a safe fallback for configuration.

    This is intentionally narrower than ``source_supports_column_selection``: the latter
    also includes sources whose columns are projected generically after extraction.
    """
    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception as e:
        capture_exception(e)
        # Unknown source types already fail the broader column-selection check. Keep the
        # read path available so a registry failure does not also blank column descriptions.
        return False
    return bool(source.supports_column_selection)
