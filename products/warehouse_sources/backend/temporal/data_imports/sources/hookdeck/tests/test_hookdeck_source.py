import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hookdeck import (
    HookdeckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    ENDPOINTS,
    HOOKDECK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.source import HookdeckSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.source"

INCREMENTAL_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if c.incremental_fields)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if not c.incremental_fields)


def _make_inputs(schema_name: str = "events", **overrides):
    defaults = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestHookdeckSource:
    def setup_method(self) -> None:
        self.source = HookdeckSource()
        self.team_id = 123
        self.config = HookdeckSourceConfig(api_key="hd_test_key")

    def test_non_retryable_errors_match_the_error_the_api_raises(self) -> None:
        observed = "401 Client Error: Unauthorized for url: https://api.hookdeck.com/2025-07-01/events?limit=250"

        assert any(key in observed for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_merge_with_a_lookback(self, name: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[name]

        assert schema.supports_incremental is True
        # Hookdeck restates rows as retries land, so a re-read window is merged, never appended.
        assert schema.supports_append is False
        assert schema.default_incremental_lookback_seconds == 24 * 60 * 60
        assert {f["field"] for f in schema.incremental_fields} == {
            f["field"] for f in HOOKDECK_ENDPOINTS[name].incremental_fields
        }

    @pytest.mark.parametrize("name", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_advertise_no_cursor(self, name: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[name]

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events", "attempts"])

        assert {s.name for s in schemas} == {"events", "attempts"}

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected",
        [
            ((True, 200), None, (True, None)),
            ((False, 401), None, (False, "Invalid Hookdeck API key")),
            # A 403 at source-create is a per-resource restriction, not a bad key.
            ((False, 403), None, (True, None)),
            ((False, 403), "events", (False, "Your Hookdeck API key can't access this resource")),
            ((False, None), None, (False, "Could not connect to the Hookdeck API")),
            ((False, 500), None, (False, "Could not connect to the Hookdeck API")),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_hookdeck_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, schema_name, expected) -> None:
        mock_validate.return_value = probe_result

        assert self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name) == expected
        mock_validate.assert_called_once_with("hd_test_key", "2025-07-01")

    @mock.patch(f"{SOURCE_MODULE}.hookdeck_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hookdeck_source) -> None:
        inputs = _make_inputs(
            schema_name="issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
            incremental_field="last_seen_at",
        )
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_hookdeck_source.call_args.kwargs
        assert kwargs["api_key"] == "hd_test_key"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "last_seen_at"

    @pytest.mark.parametrize("pinned, expected", [(None, "2025-07-01"), ("2025-01-01", "2025-01-01")])
    @mock.patch(f"{SOURCE_MODULE}.hookdeck_source")
    def test_source_for_pipeline_resolves_the_api_version(self, mock_hookdeck_source, pinned, expected) -> None:
        self.source.source_for_pipeline(self.config, mock.MagicMock(), _make_inputs(api_version=pinned))

        assert mock_hookdeck_source.call_args.kwargs["api_version"] == expected

    @mock.patch(f"{SOURCE_MODULE}.hookdeck_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_hookdeck_source) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_hookdeck_source.call_args.kwargs["db_incremental_field_last_value"] is None
