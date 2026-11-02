from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.eppo import (
    BASE_URL,
    _build_params,
    _format_since,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import PAGE_LIMIT
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source import EppoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eppo import EppoSourceConfig


class TestFormatSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_incremental_endpoint_with_cursor_adds_created_since(self) -> None:
        params = _build_params(
            "Experiments",
            incremental_field="created_date",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"created_since": "2026-03-04T02:58:14Z"}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # Metrics has no server-side timestamp filter; a cursor must not leak into the request.
        params = _build_params(
            "Metrics",
            incremental_field=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}


class TestEppoSourcePagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(EppoSource(), EppoSourceConfig(api_key="key"))

    def test_paginated_endpoint_stops_on_short_page(self) -> None:
        result = self._driver().run(
            "Experiments",
            [
                ScriptedResponse(json=[{"id": i} for i in range(PAGE_LIMIT)]),
                ScriptedResponse(json=[{"id": PAGE_LIMIT}]),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_LIMIT + 1
        assert len(result.requests) == 2
        assert result.requests[0].url.startswith(f"{BASE_URL}/experiments?")
        assert result.params("limit") == [str(PAGE_LIMIT), str(PAGE_LIMIT)]
        assert result.params("offset") == ["0", str(PAGE_LIMIT)]

    @parameterized.expand(
        [
            ("Tags", f"{BASE_URL}/tags"),
            ("EntityDefinitions", f"{BASE_URL}/definitions/entities"),
            ("FactDefinitions", f"{BASE_URL}/definitions/facts"),
            ("DimensionDefinitions", f"{BASE_URL}/definitions/dimensions"),
        ]
    )
    def test_unpaginated_endpoint_fetches_single_page_with_no_offset_params(
        self, endpoint: str, expected_url: str
    ) -> None:
        # A full-limit-sized page would normally imply another page exists, but none of these
        # endpoints document offset/limit — they must not be treated as paginated. Eppo ignores
        # the params, so an offset paginator would re-fetch the same full page forever.
        result = self._driver().run(endpoint, [ScriptedResponse(json=[{"id": i} for i in range(PAGE_LIMIT)])])

        assert result.raised is None
        assert len(result.rows) == PAGE_LIMIT
        assert len(result.requests) == 1
        assert result.requests[0].url == expected_url
        assert result.queries == [{}]

    def test_auth_is_framework_api_key(self) -> None:
        result = self._driver().run("Environments", [ScriptedResponse(json=[{"id": 1}])])

        assert result.raised is None
        assert result.requests[0].headers["x-eppo-token"] == "key"

    def test_sync_client_refuses_off_origin_redirect(self) -> None:
        # A 3xx from the Eppo API must not be followed — otherwise the X-Eppo-Token header would be
        # replayed to the redirect target. The client is pinned with allow_redirects=False.
        result = self._driver().run(
            "Experiments",
            [ScriptedResponse(status=302, headers={"Location": "https://evil.example/steal"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
        assert len(result.requests) == 1
        assert result.paths == ["/api/v1/experiments"]

    def test_incremental_cursor_added_to_request(self) -> None:
        result = self._driver().run(
            "Experiments",
            [ScriptedResponse(json=[{"id": 1}])],
            incremental_field="created_date",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("created_since") == "2026-03-04T02:58:14Z"

    def test_static_params_present_for_feature_flags_and_audiences(self) -> None:
        flags = self._driver().run("FeatureFlags", [ScriptedResponse(json=[{"id": 1}])])
        assert flags.raised is None
        assert flags.requests[0].param("include_archived") == "true"

        audiences = self._driver().run("Audiences", [ScriptedResponse(json=[{"id": 1}])])
        assert audiences.raised is None
        assert audiences.requests[0].param("status") == "all"

    @parameterized.expand(
        [
            ("Experiments", ["id"]),
            ("Metrics", ["id"]),
            ("MetricCollections", ["id"]),
            ("FeatureFlags", ["id"]),
            ("Bandits", ["id"]),
            ("Holdouts", ["id"]),
            ("Teams", ["id"]),
            ("Tags", ["id"]),
            ("Audiences", ["id"]),
            ("Environments", ["id"]),
            ("EntityDefinitions", ["id"]),
            ("FactDefinitions", ["id"]),
            ("DimensionDefinitions", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json=[{"id": 1}])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected_keys

    @parameterized.expand(
        [
            ("Experiments", "created_date"),
            ("Metrics", "created_date"),
            ("MetricCollections", None),
            ("FeatureFlags", "created_at"),
            ("Bandits", "created_at"),
            ("Holdouts", "created_at"),
            ("Teams", None),
            ("Tags", "created_at"),
            ("Audiences", "created_at"),
            ("Environments", "created_at"),
            ("EntityDefinitions", None),
            ("FactDefinitions", None),
            ("DimensionDefinitions", None),
        ]
    )
    def test_partition_keys_per_endpoint(self, endpoint: str, expected_partition: str | None) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json=[{"id": 1}])])

        assert result.raised is None
        assert result.response is not None

        if expected_partition is None:
            assert result.response.partition_keys is None
            assert result.response.partition_mode is None
        else:
            assert result.response.partition_keys == [expected_partition]
            assert result.response.partition_mode == "datetime"


class TestValidateCredentials:
    def test_probes_experiments_endpoint_with_token_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key")

        assert network.requests_log[0].url == f"{BASE_URL}/experiments?limit=1"
        assert network.requests_log[0].headers["x-eppo-token"] == "key"

    def test_probe_session_disables_redirects(self) -> None:
        # The probe carries the token; a redirect must not be followed off the validated Eppo host.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key")

        assert network.session_options[0]["allow_redirects"] is False
