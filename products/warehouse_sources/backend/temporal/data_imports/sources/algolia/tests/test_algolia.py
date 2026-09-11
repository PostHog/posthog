import json
import dataclasses
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import (
    AlgoliaResumeConfig,
    InvalidApplicationIdError,
    _base_url,
    _endpoint_url,
    algolia_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import ALGOLIA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the algolia module.
ALGOLIA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AlgoliaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT PREPARE TIME.

    ``request.params`` / ``request.json`` are single dicts mutated in place across pages, so
    inspecting them after the run shows only the final state — snapshot copies when each request
    is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": dict(request.json) if request.json is not None else None,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _build(endpoint: str, manager: mock.MagicMock, index_name: str | None = "idx", region: str = "us") -> Any:
    return algolia_source(
        endpoint=endpoint,
        application_id="APP",
        api_key="key",
        index_name=index_name,
        team_id=1,
        job_id="job",
        manager=manager,
        region=region,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBaseUrl:
    def test_builds_per_application_host(self) -> None:
        assert _base_url("MYAPPID") == "https://MYAPPID.algolia.net"

    @pytest.mark.parametrize("bad", ["evil.com/", "app id", "app.algolia.net", "a/b", "app#x", ""])
    def test_rejects_non_alphanumeric_application_id(self, bad: str) -> None:
        # The application_id is interpolated into the request host, so anything that could
        # break out of *.algolia.net must be rejected before a request is made.
        with pytest.raises(InvalidApplicationIdError):
            _base_url(bad)


class TestEndpointUrl:
    def test_formats_index_into_path(self) -> None:
        url = _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], "my_index")
        assert url == "https://APP.algolia.net/1/indexes/my_index/browse"

    def test_quotes_index_name(self) -> None:
        url = _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], "my index/slash")
        assert url == "https://APP.algolia.net/1/indexes/my%20index%2Fslash/browse"

    def test_index_scoped_endpoint_requires_index(self) -> None:
        with pytest.raises(ValueError):
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], None)

    def test_app_level_endpoint_ignores_index(self) -> None:
        assert _endpoint_url("APP", ALGOLIA_ENDPOINTS["indices"], None) == "https://APP.algolia.net/1/indexes"

    def test_analytics_endpoint_uses_regional_analytics_host(self) -> None:
        # Analytics endpoints live on the region-specific analytics host, not the per-application
        # search host, and keep the index out of the path (it rides as a query param instead).
        assert (
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["top_searches"], "idx", "us")
            == "https://analytics.algolia.com/2/searches"
        )
        assert (
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["top_searches"], "idx", "de")
            == "https://analytics.de.algolia.com/2/searches"
        )

    def test_abtests_endpoint_is_application_level_on_analytics_host(self) -> None:
        assert (
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["ab_tests"], None, "us") == "https://analytics.algolia.com/3/abtests"
        )


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_until_cursor_absent(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        calls = _wire(
            session,
            [
                _response({"hits": [{"objectID": "1"}], "cursor": "c1"}),
                _response({"hits": [{"objectID": "2"}]}),
            ],
        )

        rows = _rows(_build("records", manager))

        assert [r["objectID"] for r in rows] == ["1", "2"]
        assert [c["method"] for c in calls] == ["POST", "POST"]
        assert calls[0]["url"] == "https://APP.algolia.net/1/indexes/idx/browse"
        # First browse request carries no cursor; the second carries the cursor returned first.
        assert calls[0]["json"] == {"hitsPerPage": 1000}
        assert calls[1]["json"] == {"hitsPerPage": 1000, "cursor": "c1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_after_non_terminal_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(
            session,
            [
                _response({"hits": [{"objectID": "1"}], "cursor": "c1"}),
                _response({"hits": [{"objectID": "2"}]}),
            ],
        )

        _rows(_build("records", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AlgoliaResumeConfig(cursor="c1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_saves_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"hits": [{"objectID": "only"}]})])

        rows = _rows(_build("records", manager))

        assert [r["objectID"] for r in rows] == ["only"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(AlgoliaResumeConfig(cursor="resumed"))
        calls = _wire(session, [_response({"hits": [{"objectID": "x"}]})])

        _rows(_build("records", manager))

        assert calls[0]["json"] == {"hitsPerPage": 1000, "cursor": "resumed"}


class TestPagePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_endpoint_stops_on_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        # Fewer rows than the requested page size signals the last page for search endpoints.
        calls = _wire(session, [_response({"hits": [{"objectID": "s1"}], "nbHits": 1})])

        rows = _rows(_build("synonyms", manager))

        assert [r["objectID"] for r in rows] == ["s1"]
        assert len(calls) == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_endpoint_walks_multiple_pages(
        self, MockSession: mock.MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        monkeypatch.setitem(
            ALGOLIA_ENDPOINTS, "synonyms", dataclasses.replace(ALGOLIA_ENDPOINTS["synonyms"], page_size=2)
        )
        calls = _wire(
            session,
            [
                _response({"hits": [{"objectID": "a"}, {"objectID": "b"}], "nbHits": 3}),
                _response({"hits": [{"objectID": "c"}], "nbHits": 3}),
            ],
        )

        rows = _rows(_build("synonyms", manager))

        assert [r["objectID"] for r in rows] == ["a", "b", "c"]
        # Search endpoints page via the POST body.
        assert [c["json"]["page"] for c in calls] == [0, 1]
        assert all(c["json"]["hitsPerPage"] == 2 for c in calls)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AlgoliaResumeConfig(page=1)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_indices_uses_nb_pages_to_terminate(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        calls = _wire(
            session,
            [
                _response({"items": [{"name": "i1"}], "nbPages": 2}),
                _response({"items": [{"name": "i2"}], "nbPages": 2}),
            ],
        )

        rows = _rows(_build("indices", manager, index_name=None))

        assert [r["name"] for r in rows] == ["i1", "i2"]
        assert len(calls) == 2
        # GET endpoints page via query params, and must request the configured page size so the
        # listing doesn't fall back to Algolia's small server-side default.
        assert [c["method"] for c in calls] == ["GET", "GET"]
        assert [c["params"]["page"] for c in calls] == [0, 1]
        assert all(c["params"]["hitsPerPage"] == ALGOLIA_ENDPOINTS["indices"].page_size for c in calls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(AlgoliaResumeConfig(page=3))
        calls = _wire(session, [_response({"items": [{"name": "i"}], "nbPages": 4})])

        _rows(_build("indices", manager, index_name=None))

        assert calls[0]["params"]["page"] == 3


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_analytics_endpoint_stops_on_short_page(
        self, MockSession: mock.MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        monkeypatch.setitem(
            ALGOLIA_ENDPOINTS, "top_searches", dataclasses.replace(ALGOLIA_ENDPOINTS["top_searches"], page_size=2)
        )
        calls = _wire(
            session,
            [
                _response({"searches": [{"search": "a"}, {"search": "b"}]}),
                _response({"searches": [{"search": "c"}]}),
            ],
        )

        rows = _rows(_build("top_searches", manager))

        assert [r["search"] for r in rows] == ["a", "b", "c"]
        # The index and click-analytics flag ride as static query params; the paginator supplies
        # offset/limit. A short final page (fewer rows than the limit) ends the walk.
        assert [c["method"] for c in calls] == ["GET", "GET"]
        assert calls[0]["url"] == "https://analytics.algolia.com/2/searches"
        assert calls[0]["params"] == {"index": "idx", "clickAnalytics": "true", "offset": 0, "limit": 2}
        assert calls[1]["params"]["offset"] == 2
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AlgoliaResumeConfig(offset=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_abtests_terminates_on_total_and_omits_index(
        self, MockSession: mock.MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        monkeypatch.setitem(
            ALGOLIA_ENDPOINTS, "ab_tests", dataclasses.replace(ALGOLIA_ENDPOINTS["ab_tests"], page_size=1)
        )
        calls = _wire(
            session,
            [
                _response({"abtests": [{"abTestID": 1}], "total": 2}),
                _response({"abtests": [{"abTestID": 2}], "total": 2}),
            ],
        )

        rows = _rows(_build("ab_tests", manager, index_name=None))

        assert [r["abTestID"] for r in rows] == [1, 2]
        # A/B tests are application-level, so no index param is sent; the `total` field stops paging.
        assert "index" not in calls[0]["params"]
        assert [c["params"]["offset"] for c in calls] == [0, 1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(AlgoliaResumeConfig(offset=5))
        calls = _wire(session, [_response({"searches": []})])

        _rows(_build("top_searches", manager))

        assert calls[0]["params"]["offset"] == 5


class TestAlgoliaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ALGOLIA_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_match_settings(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        MockSession.return_value.headers = {}
        response = _build(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ALGOLIA_ENDPOINTS[endpoint].primary_keys

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_items_is_lazy(self, MockSession: mock.MagicMock) -> None:
        # Building the SourceResponse must not issue any request; only iterating items should.
        session = MockSession.return_value
        session.headers = {}
        _build("records", _make_manager())
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_application_id_header_is_set_on_session(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"hits": []})])

        _rows(_build("records", _make_manager()))

        assert session.headers.get("X-Algolia-Application-Id") == "APP"


class TestValidateCredentials:
    def _run(self, response: Any, **kwargs: Any) -> tuple[bool, str | None]:
        with mock.patch(ALGOLIA_SESSION_PATCH) as factory:
            session = factory.return_value
            session.get.return_value = response
            session.post.return_value = response
            return validate_credentials(application_id="APP", api_key="key", **kwargs)

    def test_ok(self) -> None:
        valid, error = self._run(_response({}, status_code=200), index_name="idx")
        assert valid is True
        assert error is None

    def test_invalid_credentials(self) -> None:
        resp = _response({"message": "Invalid Application-ID or API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "Invalid Algolia Application ID or API key" in error

    def test_missing_acl_accepted_at_source_create(self) -> None:
        # A genuine key lacking the ACL for the probe returns a different 403; at source
        # create (no schema_name) we accept it.
        resp = _response({"message": "Method not allowed with this API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx")
        assert valid is True
        assert error is None

    def test_missing_acl_rejected_for_specific_schema(self) -> None:
        resp = _response({"message": "Method not allowed with this API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx", schema_name="synonyms")
        assert valid is False
        assert error is not None

    def test_analytics_schema_probe_hits_regional_analytics_host(self) -> None:
        # Probing an analytics schema must target the region's analytics host (not the search host)
        # with the configured index, so the `analytics` ACL is what actually gets checked.
        with mock.patch(ALGOLIA_SESSION_PATCH) as factory:
            session = factory.return_value
            session.get.return_value = _response({}, status_code=200)
            valid, error = validate_credentials(
                application_id="APP",
                api_key="key",
                index_name="idx",
                schema_name="top_searches",
                region="de",
            )
        assert valid is True and error is None
        args, kwargs = session.get.call_args
        assert args[0] == "https://analytics.de.algolia.com/2/searches"
        assert kwargs["params"]["index"] == "idx"

    def test_invalid_application_id_rejected_before_request(self) -> None:
        with mock.patch(ALGOLIA_SESSION_PATCH) as factory:
            valid, error = validate_credentials(application_id="evil.com/", api_key="key", index_name="idx")
        assert valid is False
        assert error is not None
        factory.return_value.get.assert_not_called()
        factory.return_value.post.assert_not_called()

    def test_network_error_returns_message(self) -> None:
        with mock.patch(ALGOLIA_SESSION_PATCH) as factory:
            factory.return_value.get.side_effect = requests.ConnectionError("boom")
            valid, error = validate_credentials(application_id="APP", api_key="key")
        assert valid is False
        assert error is not None and "boom" in error

    def test_unexpected_status_returns_message(self) -> None:
        valid, error = self._run(_response({}, status_code=500), index_name="idx")
        assert valid is False
        assert error is not None and "500" in error

    def test_not_found_returns_actionable_message(self) -> None:
        # A 404 means the probed index (or application ID) doesn't exist. Give the user something to
        # act on instead of a bare "returned status 404".
        resp = _response({"message": "Index does not exist"}, status_code=404)
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None
        assert "Application ID" in error and "index" in error

    def test_unexpected_status_surfaces_algolia_message(self) -> None:
        # A non-404 error carrying an Algolia message should surface it so the user isn't left with
        # only a status code.
        resp = _response({"message": "Request rejected"}, status_code=400)
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "Request rejected" in error

    def test_non_json_error_body_does_not_crash(self) -> None:
        # A non-JSON error body (e.g. an HTML 502 page) must not blow up validation; fall back to a
        # status-based message.
        resp = mock.MagicMock()
        resp.status_code = 502
        resp.ok = False
        resp.json.side_effect = ValueError("no json")
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "502" in error
