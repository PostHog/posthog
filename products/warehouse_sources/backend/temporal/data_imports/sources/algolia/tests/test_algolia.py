import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import (
    AlgoliaResumeConfig,
    InvalidApplicationIdError,
    _base_url,
    _endpoint_url,
    _to_start_date,
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


def _driver() -> SourceDriver:
    return SourceDriver(AlgoliaSource(), AlgoliaSourceConfig(application_id="APP", api_key="key", index_name="idx"))


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
        selector = "attributes" if endpoint == "top_filter_values" else ALGOLIA_ENDPOINTS[endpoint].data_selector
        result = _driver().run(endpoint, [ScriptedResponse(json={selector: []})])

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

    def test_fanout_schema_probe_targets_the_parent_listing(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            valid, error = validate_credentials(
                application_id="APP",
                api_key="key",
                index_name="idx",
                schema_name="top_filter_values",
            )
        assert valid is True and error is None
        assert network.requests_log[0].method == "GET"
        assert network.requests_log[0].origin == "https://analytics.algolia.com"
        assert network.requests_log[0].path == "/2/filters"
        assert network.requests_log[0].param("limit") == "1"

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


class TestTimeSeriesEndpoints:
    def test_incremental_sync_sends_start_date_from_the_watermark(self) -> None:
        result = _driver().run(
            "users_count",
            [ScriptedResponse(json={"dates": [{"date": "2026-03-19", "count": 4}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-19",
            incremental_field="date",
        )

        assert result.raised is None
        assert result.params("startDate") == ["2026-03-16"]


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
