import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shutterstock import (
    ShutterstockAuthMethodConfig,
    ShutterstockSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.settings import (
    ENDPOINTS,
    SHUTTERSTOCK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.shutterstock import (
    ShutterstockAuth,
    ShutterstockResumeConfig,
    _format_start_date,
    check_endpoint_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source import ShutterstockSource

BASIC_AUTH = ShutterstockAuth(consumer_key="ck", consumer_secret="cs")
TOKEN_AUTH = ShutterstockAuth(access_token="tok")

BASIC_CONFIG = ShutterstockSourceConfig(
    auth_method=ShutterstockAuthMethodConfig(selection="api_key", consumer_key="ck", consumer_secret="cs")
)
TOKEN_CONFIG = ShutterstockSourceConfig(
    auth_method=ShutterstockAuthMethodConfig(selection="access_token", access_token="tok")
)


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "page": 1, "per_page": 100, "total_count": 999})


def _driver(config: ShutterstockSourceConfig = BASIC_CONFIG) -> SourceDriver:
    return SourceDriver(ShutterstockSource(), config)


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, 123456, tzinfo=UTC), "2026-03-04T22:13:20+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("2026-03-04T22:13:20+00:00", "2026-03-04T22:13:20+00:00"),
            ("", None),
        ],
    )
    def test_format_start_date(self, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestCredentialProbes:
    @pytest.mark.parametrize(
        "endpoint, status_code, expect_reason, expect_scope",
        [
            ("image_licenses", 200, False, None),
            ("image_licenses", 403, True, "licenses.view"),
            ("image_collections", 401, True, "collections.view"),
            ("subscriptions", 403, True, "purchases.view"),
            ("images_updated", 401, True, None),
            # A throttle or server blip is not a missing scope — the table stays selectable.
            ("image_licenses", 429, False, None),
            ("image_licenses", 500, False, None),
        ],
    )
    def test_check_endpoint_access(
        self,
        endpoint: str,
        status_code: int,
        expect_reason: bool,
        expect_scope: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            reason = check_endpoint_access(BASIC_AUTH, endpoint)

        if not expect_reason:
            assert reason is None
        else:
            assert reason is not None
            if expect_scope:
                assert expect_scope in reason


class TestGetRows:
    def test_paginates_until_empty_page_and_checkpoints(self) -> None:
        result = _driver().run("images_updated", [_page([{"id": "1"}, {"id": "2"}]), _page([])])

        assert [item["id"] for item in result.rows] == ["1", "2"]
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page")[0] == "500"
        # State saved once (after page 1, pointing at page 2); the empty page ends the run.
        assert result.saved_states == [ShutterstockResumeConfig(page=2)]

    def test_basic_auth_uses_consumer_key_and_secret(self) -> None:
        result = _driver(BASIC_CONFIG).run("images_updated", [_page([])])

        expected = base64.b64encode(b"ck:cs").decode()
        assert result.requests[0].headers["authorization"] == f"Basic {expected}"

    def test_access_token_uses_bearer_auth(self) -> None:
        result = _driver(TOKEN_CONFIG).run("image_licenses", [_page([])])

        assert result.requests[0].headers["authorization"] == "Bearer tok"

    def test_incremental_request_carries_watermark_and_ascending_sort(self) -> None:
        result = _driver().run(
            "image_licenses",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.params("start_date") == ["2026-01-01T00:00:00+00:00"]
        assert result.params("sort") == ["oldest"]
        assert result.params("per_page") == ["200"]

    def test_unpaginated_endpoint_makes_a_single_request(self) -> None:
        result = _driver().run("subscriptions", [_page([{"id": "s1"}, {"id": "s2"}])])

        assert len(result.requests) == 1
        assert [item["id"] for item in result.rows] == ["s1", "s2"]
        assert result.params("page") == [None]
        assert result.params("per_page") == [None]
        assert result.saved_states == []


class TestShutterstockSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = SHUTTERSTOCK_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, always(_page([]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SHUTTERSTOCK_ENDPOINTS.values()))
    def test_incremental_endpoints_sort_ascending_on_their_cursor(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.cursor_field is not None
            assert config.incremental_fields
            assert config.incremental_fields[0]["field"] == config.cursor_field
