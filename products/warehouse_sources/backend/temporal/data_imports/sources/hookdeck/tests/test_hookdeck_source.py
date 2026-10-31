from datetime import date

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hookdeck import (
    HookdeckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    ENDPOINTS,
    HOOKDECK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.source import HookdeckSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.source"
UNREACHABLE_MESSAGE = (
    "PostHog could not reach Hookdeck to check your API key. Wait a moment and try again, or "
    "check Hookdeck's status page."
)

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

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_merge_with_a_lookback(self, name: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[name]

        assert schema.supports_incremental is True
        # Hookdeck restates rows as retries land, so a re-read window is merged, never appended.
        assert schema.supports_append is False
        assert (
            schema.default_incremental_lookback_seconds == HOOKDECK_ENDPOINTS[name].default_incremental_lookback_seconds
        )
        assert schema.default_incremental_lookback_seconds
        assert {f["field"] for f in schema.incremental_fields} == {
            f["field"] for f in HOOKDECK_ENDPOINTS[name].incremental_fields
        }

    @pytest.mark.parametrize("name", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_advertise_no_cursor(self, name: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[name]

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected",
        [
            ((True, 200), None, (True, None)),
            (
                (False, 401),
                None,
                (
                    False,
                    "Your Hookdeck API key is invalid or has been rotated. Copy the current key from "
                    "Settings → Project → Secrets in Hookdeck, then enter it again.",
                ),
            ),
            # A 403 at source-create is a per-resource restriction, not a bad key.
            ((False, 403), None, (True, None)),
            (
                (False, 403),
                "events",
                (
                    False,
                    "Your Hookdeck API key can't access this resource. Check that the key belongs to the "
                    "project you want to sync.",
                ),
            ),
            ((False, None), None, (False, UNREACHABLE_MESSAGE)),
            ((False, 500), None, (False, UNREACHABLE_MESSAGE)),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        status_code = probe_result[1]
        script = (
            always(ScriptedResponse(status=status_code))
            if status_code is not None
            else always(requests.ConnectionError("unreachable"))
        )
        with scripted_network(script) as network:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name) == expected

        assert network.requests_log[0].path == "/2026-09-01/sources"
        assert network.requests_log[0].param("limit") == "1"

    @pytest.mark.parametrize("pinned", ["2025-07-01", "2026-09-01"])
    def test_validate_credentials_probes_under_the_pinned_version(self, pinned: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            self.source.validate_credentials(self.config, self.team_id, api_version=pinned)

        assert network.requests_log[0].path == f"/{pinned}/sources"
        assert network.requests_log[0].headers["authorization"] == "Bearer hd_test_key"

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

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            (None, "2026-09-01"),
            ("2025-07-01", "2025-07-01"),
            ("2026-09-01", "2026-09-01"),
            ("2025-01-01", "2025-01-01"),
        ],
    )
    def test_source_for_pipeline_resolves_the_api_version(self, pinned: str | None, expected: str) -> None:
        result = SourceDriver(self.source, self.config).run(
            "events", [ScriptedResponse(json={"models": [], "pagination": {}})], api_version=pinned
        )

        assert result.raised is None
        assert result.requests[0].path == f"/{expected}/events"

    @mock.patch(f"{SOURCE_MODULE}.hookdeck_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_hookdeck_source) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_hookdeck_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestHookdeckVersionDeprecation:
    def setup_method(self) -> None:
        self.source = HookdeckSource()

    def test_2025_07_01_is_deprecated_with_sunset_date(self) -> None:
        deprecation = self.source.get_version_deprecation("2025-07-01")
        assert deprecation is not None
        assert deprecation.sunset_at == date(2026, 7, 1)

    @pytest.mark.parametrize("version", ["2026-09-01", None])
    def test_current_version_is_not_deprecated(self, version: str | None) -> None:
        assert self.source.get_version_deprecation(version) is None
