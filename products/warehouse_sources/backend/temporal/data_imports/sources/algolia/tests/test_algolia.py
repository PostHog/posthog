import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import (
    AlgoliaResumeConfig,
    InvalidApplicationIdError,
    _base_url,
    _endpoint_url,
    _to_start_date,
    _to_start_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import ALGOLIA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source import AlgoliaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.algolia import (
    AlgoliaSourceConfig,
)


def _driver(region: Literal["us", "de"] = "us") -> SourceDriver:
    return SourceDriver(
        AlgoliaSource(), AlgoliaSourceConfig(application_id="APP", api_key="key", index_name="idx", region=region)
    )


def _ingestion_page(key: str, rows: list[dict[str, Any]], page: int = 1, nb_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            key: rows,
            "pagination": {"nbPages": nb_pages, "page": page, "nbItems": len(rows), "itemsPerPage": 100},
            "window": {"startDate": "2026-10-19T00:00:00Z", "endDate": "2026-10-26T00:00:00Z"},
        }
    )


class TestBaseUrl:
    @pytest.mark.parametrize("bad", ["evil.com/", "app id", "app.algolia.net", "a/b", "app#x", ""])
    def test_rejects_non_alphanumeric_application_id(self, bad: str) -> None:
        # The application_id is interpolated into the request host, so anything that could
        # break out of *.algolia.net must be rejected before a request is made.
        with pytest.raises(InvalidApplicationIdError):
            _base_url(bad)


class TestEndpointUrl:
    def test_quotes_index_name(self) -> None:
        url = _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], "my index/slash")
        assert url == "https://APP.algolia.net/1/indexes/my%20index%2Fslash/browse"

    def test_index_scoped_endpoint_requires_index(self) -> None:
        with pytest.raises(ValueError):
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], None)


class TestCursorPagination:
    def test_pages_until_cursor_absent(self) -> None:
        result = _driver().run(
            "records",
            [
                ScriptedResponse(json={"hits": [{"objectID": "1"}], "cursor": "c1"}),
                ScriptedResponse(json={"hits": [{"objectID": "2"}]}),
            ],
        )

        assert result.raised is None
        assert [row["objectID"] for row in result.rows] == ["1", "2"]
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.urls[0].lower() == "https://app.algolia.net/1/indexes/idx/browse"
        # First browse request carries no cursor; the second carries the cursor returned first.
        assert result.requests[0].json() == {"hitsPerPage": 1000}
        assert result.requests[1].json() == {"hitsPerPage": 1000, "cursor": "c1"}

    def test_resume_seeds_cursor(self) -> None:
        result = _driver().run(
            "records",
            [ScriptedResponse(json={"hits": [{"objectID": "x"}]})],
            resume_state=AlgoliaResumeConfig(cursor="resumed"),
        )

        assert result.raised is None
        assert result.requests[0].json() == {"hitsPerPage": 1000, "cursor": "resumed"}


class TestPagePagination:
    def test_search_endpoint_stops_on_short_page(self) -> None:
        # Fewer rows than the requested page size signals the last page for search endpoints.
        result = _driver().run("synonyms", [ScriptedResponse(json={"hits": [{"objectID": "s1"}], "nbHits": 1})])

        assert result.raised is None
        assert [row["objectID"] for row in result.rows] == ["s1"]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_indices_uses_nb_pages_to_terminate(self) -> None:
        result = _driver().run(
            "indices",
            [
                ScriptedResponse(json={"items": [{"name": "i1"}], "nbPages": 2}),
                ScriptedResponse(json={"items": [{"name": "i2"}], "nbPages": 2}),
            ],
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["i1", "i2"]
        assert len(result.requests) == 2
        # GET endpoints page via query params, and must request the configured page size so the
        # listing doesn't fall back to Algolia's small server-side default.
        assert [request.method for request in result.requests] == ["GET", "GET"]
        assert result.params("page") == ["0", "1"]
        assert result.params("hitsPerPage") == ["1000", "1000"]

    def test_resume_seeds_page(self) -> None:
        result = _driver().run(
            "indices",
            [ScriptedResponse(json={"items": [{"name": "i"}], "nbPages": 4})],
            resume_state=AlgoliaResumeConfig(page=3),
        )

        assert result.raised is None
        assert result.params("page") == ["3"]


class TestOffsetPagination:
    def test_abtests_terminates_on_total_and_omits_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(
            ALGOLIA_ENDPOINTS, "ab_tests", dataclasses.replace(ALGOLIA_ENDPOINTS["ab_tests"], page_size=1)
        )
        result = _driver().run(
            "ab_tests",
            [
                ScriptedResponse(json={"abtests": [{"abTestID": 1}], "total": 2}),
                ScriptedResponse(json={"abtests": [{"abTestID": 2}], "total": 2}),
            ],
        )

        assert result.raised is None
        assert [row["abTestID"] for row in result.rows] == [1, 2]
        # A/B tests are application-level, so no index param is sent; the `total` field stops paging.
        assert result.requests[0].param("index") is None
        assert result.params("offset") == ["0", "1"]

    def test_api_log_pages_by_length_on_the_search_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(
            ALGOLIA_ENDPOINTS, "api_logs", dataclasses.replace(ALGOLIA_ENDPOINTS["api_logs"], page_size=1)
        )
        result = _driver().run(
            "api_logs",
            [
                ScriptedResponse(json={"logs": [{"sha1": "a", "timestamp": "2026-10-26T10:00:00Z"}]}),
                ScriptedResponse(json={"logs": []}),
            ],
        )

        assert result.raised is None
        assert [row["sha1"] for row in result.rows] == ["a"]
        assert result.urls[0].lower().startswith("https://app.algolia.net/1/logs?")
        assert result.params("offset") == ["0", "1"]
        assert result.params("length") == ["1", "1"]
        # The log is application-wide, and the search-only page size param is not a documented param here.
        assert result.params("hitsPerPage") == [None, None]
        assert result.params("index") == [None, None]

    def test_resume_seeds_offset(self) -> None:
        result = _driver().run(
            "top_searches",
            [ScriptedResponse(json={"searches": []})],
            resume_state=AlgoliaResumeConfig(offset=5),
        )

        assert result.raised is None
        assert result.params("offset") == ["5"]


class TestAlgoliaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ALGOLIA_ENDPOINTS.keys()))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        config = ALGOLIA_ENDPOINTS[endpoint]
        # A fan-out reads its parent first, so an empty parent answers the whole run.
        first = ALGOLIA_ENDPOINTS[config.fanout.parent_name] if config.fanout else config
        body: Any = [] if first.data_selector == "$" else {first.data_selector: []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ALGOLIA_ENDPOINTS[endpoint].primary_keys


class TestValidateCredentials:
    def _run(self, response: ScriptedResponse | BaseException, **kwargs: Any) -> tuple[bool, str | None]:
        # The real stack retries a dropped connection, so an error repeats on every try.
        with scripted_network(always(response) if isinstance(response, BaseException) else [response]):
            return validate_credentials(application_id="APP", api_key="key", **kwargs)

    def test_invalid_credentials(self) -> None:
        resp = ScriptedResponse(status=403, json={"message": "Invalid Application-ID or API key", "status": 403})
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "Invalid Algolia Application ID or API key" in error

    def test_missing_acl_accepted_at_source_create(self) -> None:
        # A genuine key lacking the ACL for the probe returns a different 403; at source
        # create (no schema_name) we accept it.
        resp = ScriptedResponse(status=403, json={"message": "Method not allowed with this API key", "status": 403})
        valid, error = self._run(resp, index_name="idx")
        assert valid is True
        assert error is None

    def test_missing_acl_rejected_for_specific_schema(self) -> None:
        resp = ScriptedResponse(status=403, json={"message": "Method not allowed with this API key", "status": 403})
        valid, error = self._run(resp, index_name="idx", schema_name="synonyms")
        assert valid is False
        assert error is not None

    @pytest.mark.parametrize(
        "schema_name,region,origin,path,limit",
        [
            ("top_filter_values", "us", "https://analytics.algolia.com", "/2/filters", "1"),
            ("ingestion_run_events", "us", "https://data.us.algolia.com", "/1/runs", None),
            ("ingestion_run_events", "de", "https://data.eu.algolia.com", "/1/runs", None),
            ("query_suggestions_logs", "de", "https://query-suggestions.eu.algolia.com", "/1/configs", None),
        ],
    )
    def test_fanout_schema_probe_targets_the_parent_listing(
        self, schema_name: str, region: Literal["us", "de"], origin: str, path: str, limit: str | None
    ) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            valid, error = validate_credentials(
                application_id="APP",
                api_key="key",
                index_name="idx",
                schema_name=schema_name,
                region=region,
            )
        assert valid is True and error is None
        assert network.requests_log[0].method == "GET"
        assert network.requests_log[0].origin == origin
        assert network.requests_log[0].path == path
        assert network.requests_log[0].param("limit") == limit

    def test_invalid_application_id_rejected_before_request(self) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials(application_id="evil.com/", api_key="key", index_name="idx")
        assert valid is False
        assert error is not None
        assert network.requests_log == []

    def test_network_error_returns_message(self) -> None:
        valid, error = self._run(requests.ConnectionError("boom"))
        assert valid is False
        assert error is not None and "boom" in error

    def test_not_found_returns_actionable_message(self) -> None:
        # A 404 means the probed index (or application ID) doesn't exist. Give the user something to
        # act on instead of a bare "returned status 404".
        resp = ScriptedResponse(status=404, json={"message": "Index does not exist"})
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None
        assert "Application ID" in error and "index" in error

    def test_unexpected_status_surfaces_algolia_message(self) -> None:
        # A non-404 error carrying an Algolia message should surface it so the user isn't left with
        # only a status code.
        resp = ScriptedResponse(status=400, json={"message": "Request rejected"})
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "Request rejected" in error

    def test_non_json_error_body_does_not_crash(self) -> None:
        # A non-JSON error body (e.g. an HTML 502 page) must not blow up validation; fall back to a
        # status-based message.
        resp = ScriptedResponse(status=502, body=b"<html>bad gateway</html>")
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "502" in error


class TestStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            # The watermark reaches a source as whatever the pipeline persisted, and the lookback
            # walks it back so days Algolia is still counting events for get re-read and merged.
            ("2026-03-20", "2026-03-17"),
            (datetime(2026, 3, 20, 11, 30, tzinfo=UTC), "2026-03-17"),
            (date(2026, 3, 20), "2026-03-17"),
            # No watermark yet, or one we can't read: send no floor and take Algolia's own window
            # rather than a date its analytics retention may reject.
            (None, None),
            ("not a date", None),
        ],
    )
    def test_floors_watermark_by_the_lookback_window(self, value: Any, expected: str | None) -> None:
        assert _to_start_date(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Runs change status after they are created, so the window starts a day before the watermark.
            ("2026-10-21T05:30:15Z", "2026-10-20T05:30:15Z"),
            ("2026-10-21T05:30:15.123+02:00", "2026-10-20T03:30:15Z"),
            (datetime(2026, 10, 21, 5, 30, tzinfo=UTC), "2026-10-20T05:30:00Z"),
            # A watermark with no zone is UTC, as the pipeline stores it.
            (datetime(2026, 10, 21, 5, 30), "2026-10-20T05:30:00Z"),
            (date(2026, 10, 21), "2026-10-20T00:00:00Z"),
            (None, None),
            ("not a date", None),
        ],
    )
    def test_ingestion_start_is_utc_rfc3339_floored_by_the_lookback_window(
        self, value: Any, expected: str | None
    ) -> None:
        assert _to_start_datetime(value) == expected


class TestIncrementalEndpoints:
    @pytest.mark.parametrize(
        "endpoint,response,watermark,field,url_prefix,start_date",
        [
            (
                "users_count",
                ScriptedResponse(json={"dates": [{"date": "2026-03-19", "count": 4}]}),
                "2026-03-19",
                "date",
                "https://analytics.algolia.com/2/users/count?",
                "2026-03-16",
            ),
            (
                "ingestion_runs",
                _ingestion_page("runs", [{"runID": "r1", "createdAt": "2026-10-21T06:00:00Z"}]),
                "2026-10-21T05:00:00Z",
                "createdAt",
                "https://data.us.algolia.com/1/runs?",
                "2026-10-20T05:00:00Z",
            ),
        ],
    )
    def test_incremental_sync_sends_start_date_from_the_watermark(
        self,
        endpoint: str,
        response: ScriptedResponse,
        watermark: str,
        field: str,
        url_prefix: str,
        start_date: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [response],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field=field,
        )

        assert result.raised is None
        assert result.urls[0].startswith(url_prefix)
        assert result.params("startDate") == [start_date]
        assert result.response is not None and result.response.sort_mode == "asc"

    def test_ingestion_runs_walk_pages_in_creation_order_until_the_last_page(self) -> None:
        result = _driver().run(
            "ingestion_runs",
            [
                _ingestion_page("runs", [{"runID": "r1"}], page=1, nb_pages=2),
                _ingestion_page("runs", [{"runID": "r2"}], page=2, nb_pages=2),
            ],
        )

        assert result.raised is None
        assert [row["runID"] for row in result.rows] == ["r1", "r2"]
        assert result.params("page") == ["1", "2"]
        assert result.params("itemsPerPage") == ["100", "100"]
        # The ascending order is what makes `sort_mode="asc"` true for this table.
        assert result.params("sort") == ["createdAt", "createdAt"]
        assert result.params("order") == ["asc", "asc"]
        # A full refresh sends no window, so Algolia applies its default of the last seven days.
        assert result.params("startDate") == [None, None]


class TestTopFilterValuesFanout:
    def test_checkpoints_completed_attributes_and_resumes_from_them(self) -> None:
        result = _driver().run(
            "top_filter_values",
            [
                ScriptedResponse(json={"attributes": [{"attribute": "brand"}, {"attribute": "color"}]}),
                ScriptedResponse(json={"values": [{"attribute": "brand", "operator": ":", "value": "acme"}]}),
                ScriptedResponse(json={"values": [{"attribute": "color", "operator": ":", "value": "red"}]}),
            ],
        )

        assert result.raised is None
        completed = [state.fanout["completed"] for state in result.saved_states if state.fanout is not None]
        assert completed[-1] == ["/2/filters/brand", "/2/filters/color"]


class TestIngestionRunEventsFanout:
    @pytest.mark.parametrize(
        "should_use_incremental_field,watermark,runs_start_date",
        [
            (False, None, None),
            # The child requests take no watermark, so it bounds which runs the fan-out reads.
            (True, "2026-10-21T05:00:00Z", "2026-10-20T05:00:00Z"),
        ],
    )
    def test_reads_each_run_from_its_creation_time(
        self, should_use_incremental_field: bool, watermark: str | None, runs_start_date: str | None
    ) -> None:
        result = _driver(region="de").run(
            "ingestion_run_events",
            [
                _ingestion_page("runs", [{"runID": "r1", "createdAt": "2026-10-21T08:00:00.5+02:00"}]),
                _ingestion_page("events", [{"eventID": "e1", "runID": "r1"}], page=1, nb_pages=2),
                _ingestion_page("events", [{"eventID": "e2", "runID": "r1"}], page=2, nb_pages=2),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=watermark,
            incremental_field="publishedAt" if should_use_incremental_field else None,
        )

        assert result.raised is None
        assert [row["eventID"] for row in result.rows] == ["e1", "e2"]
        assert result.urls[0].startswith("https://data.eu.algolia.com/1/runs?")
        assert result.requests[0].param("startDate") == runs_start_date
        assert [request.path for request in result.requests[1:]] == ["/1/runs/r1/events", "/1/runs/r1/events"]
        # Without a start, Algolia returns only the events of the last three hours. The `+` of the
        # offset must reach Algolia encoded, or it decodes to a space.
        assert [request.param("startDate") for request in result.requests[1:]] == [
            "2026-10-21T08:00:00.5+02:00",
            "2026-10-21T08:00:00.5+02:00",
        ]
        assert [request.param("page") for request in result.requests[1:]] == ["1", "2"]
        # One request series per run, so the table promises no row order.
        assert result.response is not None and result.response.sort_mode is None


class TestQuerySuggestionsLogsFanout:
    @pytest.mark.parametrize(
        "log_body",
        [
            [{"timestamp": "2026-10-26T08:03:33Z", "level": "SKIP", "message": "skipping query", "contextLevel": 0}],
            # The published schema documents a single object rather than a list.
            {"timestamp": "2026-10-26T08:03:33Z", "level": "SKIP", "message": "skipping query", "contextLevel": 0},
        ],
    )
    def test_reads_the_log_of_each_configuration(self, log_body: Any) -> None:
        result = _driver().run(
            "query_suggestions_logs",
            [
                ScriptedResponse(json=[{"appID": "APP", "indexName": "qs index/en"}]),
                ScriptedResponse(json=log_body),
            ],
        )

        assert result.raised is None
        assert result.urls == [
            "https://query-suggestions.us.algolia.com/1/configs",
            "https://query-suggestions.us.algolia.com/1/logs/qs%20index%2Fen",
        ]
        # The path takes the encoded name, but the row keeps the name as Algolia reports it.
        assert result.rows == [
            {
                "timestamp": "2026-10-26T08:03:33Z",
                "level": "SKIP",
                "message": "skipping query",
                "contextLevel": 0,
                "indexName": "qs index/en",
            }
        ]
