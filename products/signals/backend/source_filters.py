from collections.abc import Mapping

import structlog
from pydantic import JsonValue

from posthog.hogql.database.models import DatabaseField

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.filter_catalog_schema import CatalogBundle
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError
from products.signals.backend.filter_recipes import FilterPredicate, WarehouseFilterBindings
from products.signals.backend.models import SignalFilterCatalogVersion, SignalFilterSourceDefinition

logger = structlog.get_logger(__name__)

SOURCE_FILTERS_FLAG = "signals-source-filters"


@frozen
class SavedSourceFilter:
    expression: str
    catalog_version: int

    def to_config(self) -> dict[str, JsonValue]:
        return {"expression": self.expression, "catalog_version": self.catalog_version}

    @classmethod
    def from_config(cls, raw: object) -> "SavedSourceFilter":
        if (
            not isinstance(raw, dict)
            or set(raw) != {"expression", "catalog_version"}
            or not isinstance(raw["expression"], str)
            or isinstance(raw["catalog_version"], bool)
            or not isinstance(raw["catalog_version"], int)
        ):
            raise FilterValidationError("saved_filter_shape", "The saved filter is not in the stored format.")
        return cls(expression=raw["expression"], catalog_version=raw["catalog_version"])


def writes_open(
    rollout_state: SignalFilterSourceDefinition.RolloutState, *, eligible: bool, internal_flag_enabled: bool
) -> bool:
    if not eligible:
        return False
    if rollout_state == SignalFilterSourceDefinition.RolloutState.ENABLED:
        return True
    return rollout_state == SignalFilterSourceDefinition.RolloutState.INTERNAL and internal_flag_enabled


def _internal_flag_enabled(organization_id: str) -> bool:
    try:
        return feature_enabled_or_false(
            SOURCE_FILTERS_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("signals.source_filters.flag_check_failed", organization_id=organization_id)
        return False


def compile_source_filter(
    *, organization_id: str, source_product: str, source_type: str, expression: str
) -> SavedSourceFilter:
    """Validate an expression a client wants to save and pin it to the active catalog version."""
    source = (
        SignalFilterSourceDefinition.objects.filter(source_product=source_product, source_type=source_type)
        .select_related("active_catalog_version")
        .first()
    )
    unavailable = FilterValidationError("not_available", "Filters are not available for this source.")
    if source is None or source.active_catalog_version is None:
        raise unavailable
    rollout_state = SignalFilterSourceDefinition.RolloutState(source.rollout_state)
    internal_flag_enabled = (
        rollout_state == SignalFilterSourceDefinition.RolloutState.INTERNAL and _internal_flag_enabled(organization_id)
    )
    if not writes_open(
        rollout_state, eligible=source.filter_query_eligible, internal_flag_enabled=internal_flag_enabled
    ):
        raise unavailable
    catalog_version = source.active_catalog_version
    bundle = CatalogBundle.model_validate(catalog_version.bundle)
    FilterExpression(expression, {field.name: field.type for field in bundle.fields})
    return SavedSourceFilter(expression=expression, catalog_version=catalog_version.version)


def saved_filter_predicate(
    *,
    source_product: str,
    source_type: str,
    saved: SavedSourceFilter,
    columns: Mapping[str, DatabaseField],
    source_alias: str,
) -> FilterPredicate | None:
    """Bind a saved filter to the catalog version it was saved against, not the active one."""
    catalog_version = SignalFilterCatalogVersion.objects.filter(
        source__source_product=source_product, source__source_type=source_type, version=saved.catalog_version
    ).first()
    if catalog_version is None:
        raise FilterValidationError("catalog_missing", "The filter's catalog version no longer exists.")
    bindings = WarehouseFilterBindings(
        CatalogBundle.model_validate(catalog_version.bundle), columns, source_alias=source_alias
    )
    return bindings.predicate(saved.expression)
