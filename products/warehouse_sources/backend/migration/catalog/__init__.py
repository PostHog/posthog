"""Maps a vendor's connector and destination ids to PostHog source and destination types."""

from collections.abc import Mapping

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.migration.catalog.fivetran_destinations import FIVETRAN_DESTINATION_TYPES
from products.warehouse_sources.backend.migration.catalog.fivetran_sources import FIVETRAN_SOURCE_TYPES
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_TYPES: Mapping[str, Mapping[str, ExternalDataSourceType]] = {"fivetran": FIVETRAN_SOURCE_TYPES}
_DESTINATION_TYPES: Mapping[str, Mapping[str, ExternalDataDestination.Type]] = {"fivetran": FIVETRAN_DESTINATION_TYPES}


@frozen
class SourceMatch:
    source_type: ExternalDataSourceType
    # Vendor table name to PostHog table name. A table that is not here keeps its name.
    table_aliases: Mapping[str, str]
    # Vendor config key to PostHog source payload key, for non-secret fields only.
    # A dot in the PostHog key is a nested field, for example `ssh_tunnel.host`.
    config_keys: Mapping[str, str]
    # Caveats that apply to every connection of this vendor service.
    notes: tuple[str, ...] = ()


def match_source(provider: str, vendor_service: str) -> SourceMatch | None:
    source_type = _SOURCE_TYPES.get(provider, {}).get(vendor_service)
    if source_type is None:
        return None
    return SourceMatch(source_type=source_type, table_aliases={}, config_keys={})


def match_destination(provider: str, vendor_service: str) -> ExternalDataDestination.Type | None:
    return _DESTINATION_TYPES.get(provider, {}).get(vendor_service)
