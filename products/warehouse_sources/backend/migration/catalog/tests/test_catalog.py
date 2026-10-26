from collections.abc import Sequence
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.migration.catalog import match_destination, match_source
from products.warehouse_sources.backend.migration.catalog.fivetran_details import (
    FIVETRAN_CONFIG_KEYS,
    FIVETRAN_NOTES,
    FIVETRAN_TABLE_ALIASES,
)
from products.warehouse_sources.backend.migration.catalog.fivetran_sources import FIVETRAN_SOURCE_TYPES
from products.warehouse_sources.backend.migration.catalog.scripts.generate_fivetran_sources import (
    _EXTRA_MATCHES,
    _REJECTED,
)
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

# The backend declares the SSH tunnel as one opaque field. These are the non-secret paths inside it
# that the connect form reads, from `SSH_FIELD` in `sourceWizardLogic.tsx`.
_SSH_TUNNEL_PATHS = frozenset({"host", "port", "auth.username"})


def _is_non_secret_field(fields: Sequence[Any], path: list[str]) -> bool:
    for field in fields:
        if field.name != path[0]:
            continue
        rest = path[1:]
        if isinstance(field, SourceFieldSSHTunnelConfig):
            return ".".join(rest) in _SSH_TUNNEL_PATHS
        if not rest:
            return isinstance(field, SourceFieldInputConfig) and not field.secret
        if isinstance(field, SourceFieldSwitchGroupConfig):
            return _is_non_secret_field(field.fields, rest)
        if isinstance(field, SourceFieldSelectConfig):
            return any(_is_non_secret_field(option.fields or [], rest) for option in field.options)
        return False
    return False


class TestCatalog:
    def test_every_fivetran_source_match_is_a_registered_source(self) -> None:
        registered = set(SourceRegistry.get_all_sources())
        unregistered = {
            service: str(source_type)
            for service, source_type in FIVETRAN_SOURCE_TYPES.items()
            if source_type not in registered
        }
        assert unregistered == {}

    def test_generated_map_matches_the_generator_overrides(self) -> None:
        assert {service: FIVETRAN_SOURCE_TYPES.get(service) for service in _EXTRA_MATCHES} == _EXTRA_MATCHES
        assert _REJECTED & set(FIVETRAN_SOURCE_TYPES) == set()

    def test_curated_details_only_name_matched_services(self) -> None:
        curated = set(FIVETRAN_TABLE_ALIASES) | set(FIVETRAN_CONFIG_KEYS) | set(FIVETRAN_NOTES)
        assert curated - set(FIVETRAN_SOURCE_TYPES) == set()

    def test_every_table_alias_points_at_a_posthog_table(self) -> None:
        missing: dict[str, list[str]] = {}
        for service, aliases in FIVETRAN_TABLE_ALIASES.items():
            source = SourceRegistry.get_source(FIVETRAN_SOURCE_TYPES[service])
            # A source that needs credentials to list its tables still documents each one.
            if source.lists_tables_without_credentials:
                tables = {table["name"] for table in source.get_documented_tables()}
            else:
                tables = set(source.get_canonical_descriptions())
            unknown = sorted(set(aliases.values()) - tables)
            if unknown:
                missing[service] = unknown
        assert missing == {}

    def test_every_config_key_points_at_a_non_secret_source_field(self) -> None:
        invalid: dict[str, list[str]] = {}
        for service, config_keys in FIVETRAN_CONFIG_KEYS.items():
            fields = SourceRegistry.get_source(FIVETRAN_SOURCE_TYPES[service]).get_source_config.fields
            unknown = sorted(key for key in config_keys.values() if not _is_non_secret_field(fields, key.split(".")))
            if unknown:
                invalid[service] = unknown
        assert invalid == {}

    def test_match_source_carries_curated_details(self) -> None:
        stripe = match_source("fivetran", "stripe_test")
        postgres = match_source("fivetran", "postgres_rds")
        assert stripe is not None and stripe.table_aliases["charge"] == "Charge"
        assert postgres is not None and postgres.config_keys["tunnel_host"] == "ssh_tunnel.host"

    @parameterized.expand(
        [
            ("name_match", "fivetran", "google_ads", ExternalDataSourceType.GOOGLEADS),
            ("managed_database_flavor", "fivetran", "postgres_rds", ExternalDataSourceType.POSTGRES),
            ("rejected_name_match", "fivetran", "light_speed_retail", None),
            ("curated_override_of_name_match", "fivetran", "confluent_cloud", ExternalDataSourceType.KAFKA),
            ("unknown_service", "fivetran", "not_a_service", None),
            ("unknown_provider", "airbyte", "postgres", None),
        ]
    )
    def test_match_source(
        self, _name: str, provider: str, service: str, expected: ExternalDataSourceType | None
    ) -> None:
        match = match_source(provider, service)
        assert (match.source_type if match else None) == expected

    @parameterized.expand(
        [
            ("bigquery_variant", "fivetran", "managed_big_query", ExternalDataDestination.Type.BIGQUERY),
            ("postgres_variant", "fivetran", "postgres_rds_warehouse", ExternalDataDestination.Type.POSTGRES),
            ("no_posthog_destination", "fivetran", "clickhouse", None),
            ("lake_with_unknown_storage", "fivetran", "managed_data_lake", None),
            ("unknown_provider", "airbyte", "snowflake", None),
        ]
    )
    def test_match_destination(
        self, _name: str, provider: str, service: str, expected: ExternalDataDestination.Type | None
    ) -> None:
        assert match_destination(provider, service) == expected
