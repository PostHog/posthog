from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvest import (
    HarvestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import (
    ENDPOINTS,
    HARVEST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source import HarvestSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source.validate_harvest_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source.harvest_source"


def _config() -> HarvestSourceConfig:
    return HarvestSourceConfig(account_id="123456", access_token="pat-secret")


class TestHarvestSource:
    @parameterized.expand([("account_id", False), ("access_token", True)])
    def test_only_the_token_field_is_secret(self, field_name: str, expected_secret: bool) -> None:
        # A non-secret token field would be echoed back to the frontend in plain text.
        field = next(f for f in HarvestSource().get_source_config.fields if f.name == field_name)
        assert isinstance(field, SourceFieldInputConfig)
        assert field.secret is expected_secret
        assert field.required is True

    def test_api_version_pins_the_path_the_code_calls(self) -> None:
        assert HarvestSource.supported_versions == ("v2",)
        assert HarvestSource.default_version == "v2"

    @parameterized.expand([("time_entries", True), ("invoices", True), ("roles", False)])
    def test_incremental_support_tracks_the_updated_since_filter(self, name: str, expected: bool) -> None:
        # Only endpoints with a server-side `updated_since` filter may advertise incremental
        # sync; roles has none, so it must stay full refresh.
        schema = next(s for s in HarvestSource().get_schemas(_config(), team_id=1) if s.name == name)
        assert schema.supports_incremental is expected
        assert [f["field"] for f in schema.incremental_fields] == (["updated_at"] if expected else [])

    def test_documented_tables_render_without_credentials(self) -> None:
        # Static catalog -> the public docs Supported tables section renders with no connection.
        assert HarvestSource.lists_tables_without_credentials is True
        tables = HarvestSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all(t["description"] for t in tables)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Entries keyed off a stale endpoint name silently fall back to LLM enrichment.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("valid", True, None, True, None),
            ("invalid", False, 401, False, "Invalid Harvest account ID"),
            ("no_scope", False, 403, False, "does not have permission"),
            ("unreachable", False, None, False, "Could not reach Harvest"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_ok: bool, status: int | None, expected_ok: bool, expected_error: str | None
    ) -> None:
        # Distinct messages keep a 403 (missing permission) and an unreachable probe from both
        # reading as "bad credentials", which would send the user chasing the wrong fix.
        with patch(VALIDATE_PATCH, return_value=(probe_ok, status)):
            ok, error = HarvestSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        if expected_error is None:
            assert error is None
        else:
            assert error is not None and expected_error in error

    @parameterized.expand([("unpinned", None, "v2"), ("pinned", "v2", "v2")])
    def test_source_for_pipeline_plumbs_config_and_version(self, _name: str, pin: str | None, expected: str) -> None:
        inputs = MagicMock()
        inputs.schema_name = "time_entries"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.api_version = pin
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = MagicMock()

        with patch(SOURCE_PATCH) as mock_source:
            HarvestSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["account_id"] == "123456"
        assert kwargs["access_token"] == "pat-secret"
        assert kwargs["endpoint"] == "time_entries"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["api_version"] == expected
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_partition_keys_are_creation_time_only(self) -> None:
        # An `updated_at` partition key would rewrite every partition on each sync.
        partition_keys = {c.partition_key for c in HARVEST_ENDPOINTS.values() if c.partition_key}
        assert partition_keys == {"created_at"}

    def test_page_size_stays_within_the_api_cap(self) -> None:
        # Harvest rejects per_page above 2000 with a 422.
        assert all(0 < c.page_size <= 2000 for c in HARVEST_ENDPOINTS.values())

    def test_source_config_is_visible_to_users(self) -> None:
        # A truthy unreleasedSource filters the connector out of the frontend entirely.
        assert not HarvestSource().get_source_config.unreleasedSource
