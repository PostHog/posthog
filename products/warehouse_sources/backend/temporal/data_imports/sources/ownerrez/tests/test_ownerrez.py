import base64
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import (
    OwnerRezResumeConfig,
    _build_params,
    _format_since_utc,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import (
    EPOCH,
    OWNERREZ_ENDPOINTS,
    PAGE_LIMIT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source import OwnerrezSource


class TestFormatSinceUtc:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_since_utc(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_non_incremental_endpoint_never_filters(self) -> None:
        # Guests has no exposed timestamp column, so it never offers incremental sync — but the
        # API still requires created_since_utc on every request.
        params = _build_params(
            OWNERREZ_ENDPOINTS["Guests"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert params == {"limit": PAGE_LIMIT, "created_since_utc": EPOCH}

    def test_endpoint_without_since_param_never_filters(self) -> None:
        params = _build_params(
            OWNERREZ_ENDPOINTS["Properties"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"limit": PAGE_LIMIT}


def _driver() -> SourceDriver:
    return SourceDriver(OwnerrezSource(), OwnerrezSourceConfig(email="host@example.com", api_key="pt_key"))


def _page(items: list[dict[str, Any]], *, next_page_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "limit": PAGE_LIMIT, "offset": 0, "next_page_url": next_page_url})


class TestOwnerrezSourceTransport:
    @parameterized.expand([("unpinned", None), ("v1", "v1"), ("v2", "v2")])
    def test_every_version_calls_v2_paths(self, _name: str, api_version: str | None) -> None:
        result = _driver().run("Properties", [_page([{"id": 1}])], api_version=api_version)

        assert result.raised is None
        assert result.paths == ["/v2/properties"]

    def test_follows_next_page_url_until_null(self) -> None:
        result = _driver().run(
            "Properties",
            [
                _page([{"id": 1}, {"id": 2}], next_page_url="https://api.ownerrez.com/v2/properties?offset=2"),
                _page([{"id": 3}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.paths == ["/v2/properties", "/v2/properties"]
        assert result.requests[0].origin == "https://api.ownerrez.com"
        assert result.requests[0].param("limit") == str(PAGE_LIMIT)
        # The second request follows the opaque next_page_url verbatim, with no re-appended params.
        assert result.urls[1] == "https://api.ownerrez.com/v2/properties?offset=2"
        assert result.queries[1] == {"offset": ("2",)}

    def test_bookings_incremental_cursor_added_to_request(self) -> None:
        result = _driver().run(
            "Bookings",
            [_page([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("since_utc") == "2026-03-04T02:58:14Z"

    def test_resumes_from_saved_next_url(self) -> None:
        result = _driver().run(
            "Properties",
            [_page([{"id": 2}])],
            resume_state=OwnerRezResumeConfig(next_url="https://api.ownerrez.com/v2/properties?offset=1"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [2]
        assert result.urls == ["https://api.ownerrez.com/v2/properties?offset=1"]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            result = validate_credentials("host@example.com", "pt_key")

        assert result == (True, 200)
        assert [request.path for request in network.requests_log] == ["/v2/properties"]
        assert network.requests_log[0].param("limit") == "1"
        encoded = base64.b64encode(b"host@example.com:pt_key").decode()
        assert network.requests_log[0].headers["authorization"] == f"Basic {encoded}"
