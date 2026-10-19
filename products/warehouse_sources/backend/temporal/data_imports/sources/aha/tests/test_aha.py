from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha import (
    AhaResumeConfig,
    _build_initial_params,
    _format_updated_since,
    _incremental_window,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import AHA_ENDPOINTS, PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.source import AhaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aha import AhaSourceConfig


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.aha.io", "acme"),
            ("https_url", "https://acme.aha.io", "acme"),
            ("trailing_slash", "acme.aha.io/", "acme"),
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


class TestFormatUpdatedSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_full_refresh_endpoint_never_filters(self) -> None:
        # goals has no server-side `updated_since`; a cursor must not leak into the request.
        params = _build_initial_params(
            AHA_ENDPOINTS["goals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {response_key: items or []}
    if total_pages is not None:
        body["pagination"] = {"current_page": current_page or 1, "total_pages": total_pages}
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(AhaSource(), AhaSourceConfig(subdomain="acme", api_key="key"))


class TestAhaSource:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "features",
            [_response("features", [{"id": "2"}], current_page=2, total_pages=2)],
            resume_state=AhaResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert result.params("page") == ["2"]

    def test_incremental_cursor_added_to_request(self) -> None:
        result = _driver().run(
            "features",
            [_response("features", [{"id": "1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("updated_since") == ["2026-03-04T02:58:14Z"]

    def test_uses_response_key_for_todos(self) -> None:
        # to-dos live at /tasks with a `tasks` root key.
        result = _driver().run("todos", [_response("tasks", [{"id": "t1"}], total_pages=1)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["t1"]
        assert result.paths == ["/api/v1/tasks"]

    def test_missing_metadata_full_page_continues(self) -> None:
        # No pagination metadata + a full page -> there may be more pages.
        full_page = [{"id": str(i)} for i in range(PER_PAGE)]
        result = _driver().run("features", [_response("features", full_page), _response("features", [{"id": "last"}])])

        assert result.raised is None
        assert len(result.rows) == PER_PAGE + 1
        assert result.params("page") == ["1", "2"]


class TestIncrementalWindow:
    def test_binds_cursor_field_to_updated_since(self) -> None:
        window = _incremental_window("updated_at")
        assert window["cursor_path"] == "updated_at"
        assert window["start_param"] == "updated_since"
        convert = window["convert"]
        assert convert is not None
        # The convert hook must emit the trailing-Z UTC form Aha! accepts, not an isoformat offset.
        assert convert(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)) == "2026-03-04T02:58:14Z"


class TestAhaFanout:
    def test_releases_injects_product_id_from_parent(self) -> None:
        result = _driver().run(
            "releases",
            [
                _response("products", [{"id": "1000"}]),
                _response("releases", [{"id": "R1"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/products", "/api/v1/products/1000/releases"]
        assert result.rows == [{"id": "R1", "product_id": "1000"}]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("acme", "key") == (True, 200)

        assert [request.path for request in network.requests_log] == ["/api/v1/me"]

    def test_bad_subdomain_raises_before_probe(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError, match="Invalid Aha! account domain"):
                validate_credentials("acme/../evil", "key")

        assert network.requests_log == []
        assert network.session_options == []
