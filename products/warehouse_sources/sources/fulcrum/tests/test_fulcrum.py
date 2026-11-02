import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum import (
    FulcrumPageNumberPaginator,
    FulcrumResumeConfig,
    _to_epoch_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import FULCRUM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.source import FulcrumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fulcrum import (
    FulcrumSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FulcrumSource(), FulcrumSourceConfig(api_token="token"))


def _page(
    data_key: str,
    items: list[dict[str, Any]],
    *,
    total_pages: int | None = None,
    current_page: int | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if total_pages is not None:
        body["total_pages"] = total_pages
    if current_page is not None:
        body["current_page"] = current_page
    return ScriptedResponse(json=body)


class TestToEpochSeconds:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), 1609459200),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_epoch_seconds(value) == expected


class TestIncrementalParams:
    # Both endpoints filter through `updated_since`, but they key off different cursor fields
    # (records on updated_at, audit_logs on time), so the cursor comes from the endpoint config.
    @parameterized.expand(["records", "audit_logs"])
    def test_incremental_adds_updated_since(self, endpoint: str) -> None:
        config = FULCRUM_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            [_page(config.data_key, [{"id": "1"}], total_pages=1, current_page=1)],
            incremental_field=config.default_incremental_field,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        # updated_since is the epoch-seconds cutoff; per_page and page ride alongside it.
        assert result.requests[0].param("updated_since") == "1609459200"
        assert result.requests[0].param("page") == "1"
        assert result.requests[0].param("per_page") == str(config.page_size)

    @parameterized.expand(["forms", "projects", "photos", "records_history", "groups"])
    def test_non_incremental_endpoints_never_filter(self, endpoint: str) -> None:
        # A full-refresh endpoint must never send updated_since even when a watermark is present —
        # it has no server-side time filter, so the incremental config is not wired for it.
        config = FULCRUM_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            [_page(config.data_key, [{"id": "1"}], total_pages=1, current_page=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_since") is None


class TestPaginatorHeuristic:
    def _body(self, total_pages: int | None = None, current_page: int | None = None) -> Response:
        body: dict[str, Any] = {}
        if total_pages is not None:
            body["total_pages"] = total_pages
        if current_page is not None:
            body["current_page"] = current_page
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps(body).encode()
        return resp

    @parameterized.expand(
        [
            # (total_pages, current_page, items_len, expected_more)
            ("more_by_total_pages", 3, 1, 1, True),
            ("last_by_total_pages", 3, 3, 1, False),
            ("missing_total_full_page_means_more", None, None, 2, True),
            ("missing_total_short_page_means_done", None, None, 1, False),
        ]
    )
    def test_update_state(
        self, _name: str, total_pages: int | None, current_page: int | None, items_len: int, expected_more: bool
    ) -> None:
        # per_page=2 so a 2-item page is "full" and a 1-item page is "short".
        paginator = FulcrumPageNumberPaginator(per_page=2)
        data: list[dict[str, Any]] = [{}] * items_len
        paginator.update_state(self._body(total_pages, current_page), data=data)
        assert paginator.has_next_page is expected_more
        # The page advances only while more pages remain.
        assert paginator.page == (2 if expected_more else 1)


class TestPagination:
    def test_paginates_and_yields_each_page(self) -> None:
        result = _driver().run(
            "forms",
            [
                _page("forms", [{"id": "1"}], total_pages=2, current_page=1),
                _page("forms", [{"id": "2"}], total_pages=2, current_page=2),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.params("page") == ["1", "2"]
        # One checkpoint saved after the first page (pointing at page 2); the last page saves nothing.
        assert result.saved_states == [FulcrumResumeConfig(page=2)]

    def test_stops_on_empty_page(self) -> None:
        result = _driver().run("forms", [_page("forms", [], total_pages=1, current_page=1)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "forms",
            [_page("forms", [{"id": "2"}], total_pages=2, current_page=2)],
            resume_state=FulcrumResumeConfig(page=2),
        )

        assert result.raised is None
        assert result.params("page") == ["2"]
        assert len(result.requests) == 1


class TestFulcrumSource:
    @parameterized.expand(
        [
            ("records", ["id"], "created_at", "asc"),
            ("photos", ["access_key"], "created_at", "asc"),
            ("roles", ["id"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        config = FULCRUM_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page(config.data_key, [], total_pages=1, current_page=1)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_pk
        assert result.response.sort_mode == sort_mode
        if partition_key is None:
            assert result.response.partition_mode is None
        else:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_format == "week"
            assert result.response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("token") is expected

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.path == "/api/v2/forms.json"
        assert request.param("page") == "1"
        assert request.param("per_page") == "1"
        assert request.headers["x-apitoken"] == "token"


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        # Fulcrum enforces an hourly request cap (429) and can 5xx transiently; both are retried by
        # the shared client on status, so a rate limit doesn't hard-fail the whole sync.
        result = _driver().run(
            "forms",
            [
                ScriptedResponse(status=status_code, json={"error": "transient"}),
                _page("forms", [{"id": "1"}], total_pages=1, current_page=1),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert len(result.requests) == 2

    def test_client_error_fails_loud(self) -> None:
        # A 401 is a permanent credential failure — it must surface as an HTTPError, not be retried.
        result = _driver().run("forms", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestFormHistoryFanout:
    def test_resume_skips_completed_parents(self) -> None:
        # The parent listing is always re-fetched; only the child fetches are skipped.
        result = _driver().run(
            "form_history",
            [
                _page("forms", [{"id": "f1"}, {"id": "f2"}], total_pages=1, current_page=1),
                _page("forms", [{"id": "f2", "version": 3}], total_pages=1, current_page=1),
            ],
            resume_state=FulcrumResumeConfig(completed=["/forms/f1/history.json"]),
        )

        assert result.raised is None
        assert [request.origin for request in result.requests[1:]] == ["https://api.fulcrumapp.com"]
        assert result.paths[1:] == ["/api/v2/forms/f2/history.json"]
        assert [row["form_id"] for row in result.rows] == ["f2"]
