from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uservoice import (
    UservoiceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.source import UservoiceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.uservoice import (
    UservoiceResumeConfig,
    _format_updated_after,
    normalize_subdomain,
    validate_credentials,
)


def _response(response_key: str, items: list[dict[str, Any]], pagination: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={response_key: items, "pagination": pagination})


def _run(script: Script, endpoint: str = "suggestions", **kwargs: Any) -> DriveResult:
    driver = SourceDriver(UservoiceSource(), UservoiceSourceConfig(subdomain="acme", api_key="token"))
    return driver.run(endpoint, script, **kwargs)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.uservoice.com", "acme"),
            ("https_url", "https://acme.uservoice.com", "acme"),
            ("trailing_slash", "acme.uservoice.com/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(value)


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_after(value)
        assert result == expected
        assert "+00:00" not in result


class TestPagination:
    def test_paginates_by_page_number(self) -> None:
        result = _run(
            [
                _response("suggestions", [{"id": 1}, {"id": 2}], {"page": 1, "total_pages": 2}),
                _response("suggestions", [{"id": 3}], {"page": 2, "total_pages": 2}),
            ]
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3]
        assert result.params("per_page") == [str(PER_PAGE)] * 2
        assert result.params("page") == [None, "2"]
        # Checkpoint saved once after the first page (points at page 2); the last page ends it.
        assert result.saved_states == [UservoiceResumeConfig(cursor=None, page=2)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run([_response("suggestions", [{"id": 1}], {"page": 1, "total_pages": 1})])

        assert result.params("page") == [None]
        assert result.params("cursor") == [None]

    def test_stops_on_non_advancing_cursor(self) -> None:
        # A cursor that repeats itself must not loop forever, but both yielded pages are kept.
        result = _run(
            [
                _response("suggestions", [{"id": 1}], {"cursor": "SAME"}),
                _response("suggestions", [{"id": 2}], {"cursor": "SAME"}),
            ]
        )

        assert [r["id"] for r in result.rows] == [1, 2]
        assert len(result.requests) == 2

    def test_missing_meta_full_page_keeps_going(self) -> None:
        full_page = [{"id": i} for i in range(PER_PAGE)]
        result = _run([_response("suggestions", full_page, {}), _response("suggestions", [{"id": 999}], {})])

        assert len(result.rows) == PER_PAGE + 1
        assert result.params("page") == [None, "2"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _run(
            [_response("suggestions", [{"id": 9}], {})],
            resume_state=UservoiceResumeConfig(cursor="CUR9"),
        )

        assert [r["id"] for r in result.rows] == [9]
        assert result.params("cursor") == ["CUR9"]

    def test_incremental_filter_added_to_request(self) -> None:
        result = _run(
            [_response("suggestions", [{"id": 1}], {"page": 1, "total_pages": 1})],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.params("updated_after") == ["2026-03-04T02:58:14Z"]

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # labels has no server-side `updated_after`; a cursor value must not leak into the request.
        result = _run(
            [_response("labels", [{"id": 1}], {"page": 1, "total_pages": 1})],
            endpoint="labels",
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.params("updated_after") == [None]


class TestSourceResponse:
    @parameterized.expand(
        [
            # Incremental endpoints defer the watermark write to job end via "desc" (order is unverified).
            ("suggestions", "desc", "created_at"),
            ("tickets", "desc", "created_at"),
            # Full-refresh endpoints don't checkpoint a watermark, so they stay on the default "asc".
            ("labels", "asc", "created_at"),
        ]
    )
    def test_sort_mode_and_partitioning(self, endpoint: str, expected_sort: str, partition_key: str) -> None:
        response = _run([_response(endpoint, [], {})], endpoint=endpoint).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, 200),
        ]
    )
    def test_maps_status(self, _name, status, expected_ok, expected_status) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            ok, code = validate_credentials("acme", "token")

        assert ok is expected_ok
        assert code == expected_status
        assert network.requests_log[0].url == "https://acme.uservoice.com/api/v2/admin/suggestions?per_page=1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"

    def test_bad_subdomain_raises(self) -> None:
        # A malformed subdomain must surface as ValueError so the caller can show a precise message.
        with pytest.raises(ValueError):
            validate_credentials("acme/../evil", "token")
