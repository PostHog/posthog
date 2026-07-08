import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Request, Response
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom import intercom as intercom_module
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.intercom import (
    INTERCOM_API_BASE,
    IntercomSearchPaginator,
    _build_paginator,
    _build_search_body,
    _company_segments_generator,
    _conversation_parts_generator,
    _drain_company_ids,
    _is_scroll_exists,
    _is_server_error,
    _iter_companies,
    _make_intercom_session,
    get_resource,
    intercom_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS


def _make_response(json_body: Any, status_code: int = 200, text: str = "") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode() if json_body is not None else text.encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    # `EndpointResource["endpoint"]` is typed `str | Endpoint | None`; tests build dict endpoints.
    return cast(dict[str, Any], resource["endpoint"])


SCROLL_EXISTS_BODY = {
    "type": "error.list",
    "errors": [{"code": "scroll_exists", "message": "scroll already exists for this workspace"}],
}


def _http_error(json_body: Any, status_code: int = 400, text: str = "") -> HTTPError:
    return HTTPError(response=_make_response(json_body, status_code=status_code, text=text))


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,schema_name,expected_valid",
        [
            (200, None, True),
            (200, "contacts", True),
            (401, None, False),
            (401, "contacts", False),
            # 403 at source-create is accepted (token genuine, scope may be granted per-endpoint later)
            (403, None, True),
            # 403 for a specific schema means the scope is genuinely missing
            (403, "contacts", False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool):
        mock_session = mock.MagicMock()
        mock_session.get.return_value = _make_response({"type": "admin"}, status_code=status_code, text="boom")

        with mock.patch.object(intercom_module, "make_tracked_session", return_value=mock_session):
            is_valid, error = validate_credentials("token", schema_name=schema_name)

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_missing_token(self):
        is_valid, error = validate_credentials("")
        assert is_valid is False
        assert error is not None and "Missing" in error

    def test_request_exception_returns_invalid(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = Exception("connection reset")

        with mock.patch.object(intercom_module, "make_tracked_session", return_value=mock_session):
            is_valid, error = validate_credentials("token")

        assert is_valid is False
        assert error is not None and "connection reset" in error


class TestSearchPaginator:
    def test_update_state_sets_next_cursor(self):
        paginator = IntercomSearchPaginator()
        response = _make_response({"pages": {"next": {"starting_after": "cursor-123"}}})

        paginator.update_state(response)

        assert paginator.has_next_page is True
        assert paginator._next_cursor == "cursor-123"

    def test_update_state_terminal_when_no_next(self):
        paginator = IntercomSearchPaginator()
        response = _make_response({"pages": {"next": None}})

        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator._next_cursor is None

    def test_update_state_handles_bad_json(self):
        paginator = IntercomSearchPaginator()
        response = _make_response(None, text="not json")

        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_update_request_writes_cursor_into_body(self):
        paginator = IntercomSearchPaginator()
        paginator.update_state(_make_response({"pages": {"next": {"starting_after": "cursor-xyz"}}}))

        request = Request(method="POST", url=f"{INTERCOM_API_BASE}/contacts/search", json={"pagination": {}})
        paginator.update_request(request)

        assert request.json["pagination"]["starting_after"] == "cursor-xyz"

    def test_update_request_noop_without_cursor(self):
        paginator = IntercomSearchPaginator()
        request = Request(method="POST", url="http://x", json={"pagination": {}})

        paginator.update_request(request)

        assert "starting_after" not in request.json["pagination"]


class TestBuildSearchBody:
    def test_full_refresh_matches_all_records(self):
        body = _build_search_body(INTERCOM_ENDPOINTS["contacts"], "updated_at", None)

        assert body["query"] == {"field": "updated_at", "operator": ">", "value": 0}
        assert body["sort"] == {"field": "updated_at", "order": "ascending"}
        assert body["pagination"]["per_page"] == INTERCOM_ENDPOINTS["contacts"].page_size

    def test_incremental_uses_last_value(self):
        body = _build_search_body(INTERCOM_ENDPOINTS["conversations"], "updated_at", "1700000000")

        assert body["query"]["value"] == 1700000000


class TestBuildPaginator:
    @pytest.mark.parametrize(
        "kind,expected_type",
        [
            ("search", IntercomSearchPaginator),
            ("cursor", JSONResponseCursorPaginator),
            ("next_url", JSONResponsePaginator),
            ("single", SinglePagePaginator),
        ],
    )
    def test_paginator_per_kind(self, kind: str, expected_type: type):
        cfg = mock.MagicMock()
        cfg.paginator_kind = kind
        assert isinstance(_build_paginator(cfg), expected_type)


NON_SUBSTREAM_ENDPOINTS = [name for name, cfg in INTERCOM_ENDPOINTS.items() if cfg.paginator_kind != "substream"]


class TestGetResource:
    @pytest.mark.parametrize(
        "should_use_incremental,last_value,expected_disposition,expected_query_value",
        [
            (True, "1700000000", {"disposition": "merge", "strategy": "upsert"}, 1700000000),
            # Full refresh still needs a query body; value 0 matches everything.
            (False, None, "replace", 0),
        ],
    )
    def test_search_endpoint_body_and_disposition(
        self, should_use_incremental: bool, last_value: str | None, expected_disposition: Any, expected_query_value: int
    ):
        resource = get_resource(
            "contacts",
            should_use_incremental_field=should_use_incremental,
            incremental_field="updated_at" if should_use_incremental else None,
            db_incremental_field_last_value=last_value,
        )

        assert resource["write_disposition"] == expected_disposition
        endpoint = _endpoint(resource)
        assert endpoint["method"] == "POST"
        assert endpoint["json"]["query"]["value"] == expected_query_value

    @pytest.mark.parametrize(
        "should_use_incremental,last_value,expected_disposition,expected_cursor",
        [
            (True, "1700000000", {"disposition": "merge", "strategy": "upsert"}, 1700000000),
            # Full refresh sets the cursor to the Unix epoch start (matches everything).
            (False, None, "replace", 0),
        ],
    )
    def test_query_param_endpoint_cursor_and_disposition(
        self, should_use_incremental: bool, last_value: str | None, expected_disposition: Any, expected_cursor: int
    ):
        resource = get_resource(
            "activity_logs",
            should_use_incremental_field=should_use_incremental,
            incremental_field="created_at" if should_use_incremental else None,
            db_incremental_field_last_value=last_value,
        )

        assert _endpoint(resource)["params"]["created_at_after"] == expected_cursor
        assert resource["write_disposition"] == expected_disposition

    @pytest.mark.parametrize(
        "endpoint_name,expected_model",
        [("company_attributes", "company"), ("contact_attributes", "contact")],
    )
    def test_single_endpoint_with_extra_params(self, endpoint_name: str, expected_model: str):
        resource = get_resource(
            endpoint_name,
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value=None,
        )

        assert _endpoint(resource)["params"] == {"model": expected_model}

    def test_single_endpoint_without_params(self):
        resource = get_resource(
            "admins", should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )

        assert "params" not in _endpoint(resource)

    @pytest.mark.parametrize("name", NON_SUBSTREAM_ENDPOINTS)
    def test_table_format_and_name(self, name: str):
        resource = get_resource(
            name, should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )
        assert resource["name"] == name
        assert resource["table_name"] == name
        assert resource["table_format"] == "delta"


class TestSubstreamGenerators:
    def test_conversation_parts_injects_conversation_id(self):
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"conversations": [{"id": "c1"}, {"id": "c2"}], "pages": {}}),
        ]
        mock_session.get.side_effect = [
            _make_response({"conversation_parts": {"conversation_parts": [{"id": "p1"}, {"id": "p2"}]}}),
            _make_response({"conversation_parts": {"conversation_parts": [{"id": "p3"}]}}),
        ]

        parts = list(_conversation_parts_generator(mock_session, "updated_at", None))

        assert [p["id"] for p in parts] == ["p1", "p2", "p3"]
        assert {p["conversation_id"] for p in parts} == {"c1", "c2"}

    def test_conversation_parts_skips_404_parent(self):
        # A conversation listed by search can be deleted/merged before we fetch
        # its detail — Intercom 404s. Skip it instead of failing the whole sync.
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"conversations": [{"id": "c1"}, {"id": "c2"}], "pages": {}}),
        ]
        mock_session.get.side_effect = [
            _make_response(None, status_code=404, text="Not Found"),
            _make_response({"conversation_parts": {"conversation_parts": [{"id": "p3"}]}}),
        ]

        parts = list(_conversation_parts_generator(mock_session, "updated_at", None))

        assert [p["id"] for p in parts] == ["p3"]
        assert {p["conversation_id"] for p in parts} == {"c2"}

    def test_conversation_parts_reraises_non_404(self):
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"conversations": [{"id": "c1"}], "pages": {}}),
        ]
        mock_session.get.side_effect = [
            _make_response(None, status_code=500, text="Server Error"),
        ]

        with pytest.raises(HTTPError):
            list(_conversation_parts_generator(mock_session, "updated_at", None))

    def test_company_segments_skips_404_parent(self):
        # The scroll is drained fully before any per-company segment fetch, so
        # `session.get` is called in order: scroll page -> empty scroll page ->
        # segments(co1) -> segments(co2). A 404 on a single segment fetch (the
        # company vanished between listing and fetch) skips that company only.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}, {"id": "co2"}], "scroll_param": "s1"}),
            _make_response({"data": [], "scroll_param": "s2"}),
            _make_response(None, status_code=404, text="Not Found"),
            _make_response({"data": [{"id": "s2"}]}),
        ]

        segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["s2"]
        assert segments[0]["company_id"] == "co2"

    def test_company_segments_reraises_non_404(self):
        # 500 is retried inline by `_scroll_companies_get`; a non-404 on the
        # per-company segment fetch (not the scroll) must surface. Drain the
        # scroll first, then fail the segment fetch with a 500.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": []}),
            _make_response(None, status_code=500, text="Server Error"),
        ]

        with pytest.raises(HTTPError):
            list(_company_segments_generator(mock_session))

    def test_company_segments_injects_company_id(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}, {"id": "co2"}], "scroll_param": "s1"}),
            _make_response({"data": [], "scroll_param": "s2"}),
            _make_response({"data": [{"id": "s1"}]}),
            _make_response({"data": [{"id": "s2"}, {"id": "s3"}]}),
        ]

        segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["s1", "s2", "s3"]
        assert segments[0]["company_id"] == "co1"
        assert segments[1]["company_id"] == "co2"

    def test_company_segments_drains_scroll_before_fetching_segments(self):
        # Intercom expires an idle companies scroll after ~1 min. Fetching
        # segments between scroll pages let the cursor lapse mid-walk, 404ing the
        # next continuation. The scroll must be fully walked before any segment
        # fetch, so the scroll requests stay back-to-back.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": [{"id": "co2"}], "scroll_param": "s2"}),
            _make_response({"data": []}),
            _make_response({"data": [{"id": "seg1"}]}),
            _make_response({"data": [{"id": "seg2"}]}),
        ]

        segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["seg1", "seg2"]
        urls = [call.args[0] for call in mock_session.get.call_args_list]
        last_scroll = max(i for i, u in enumerate(urls) if u.endswith("/companies/scroll"))
        first_segments = min(i for i, u in enumerate(urls) if u.endswith("/segments"))
        assert last_scroll < first_segments

    def test_company_segments_restarts_scroll_on_expired_cursor(self):
        # The observed failure: the companies scroll cursor expires mid-drain and
        # the continuation 404s (GET /companies/scroll?scroll_param=...). Because ids
        # are drained before any segment is yielded, restarting the walk from the
        # beginning is safe — nothing has been written yet — so the drain re-walks
        # and the sync continues instead of failing the whole run.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            # First drain: one page, then the continuation 404s (expired scroll).
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response(None, status_code=404, text="Not Found"),
            # Restarted drain from the beginning: walks to completion.
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s2"}),
            _make_response({"data": []}),
            # Segment fetch for the drained company.
            _make_response({"data": [{"id": "seg1"}]}),
        ]

        segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["seg1"]
        assert segments[0]["company_id"] == "co1"
        # The retried open carries no scroll_param — a scroll only restarts from
        # the beginning, never resumes from the dead cursor.
        assert mock_session.get.call_args_list[2].kwargs["params"] is None

    def test_drain_company_ids_reraises_expired_cursor_after_max_retries(self):
        # A persistently-invalidated scroll must surface after the bounded retries
        # rather than re-walking forever.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response(None, status_code=404, text="Not Found")
            for _ in range(intercom_module._SCROLL_EXPIRED_MAX_RETRIES + 1)
        ]

        with pytest.raises(HTTPError):
            _drain_company_ids(mock_session)

        assert mock_session.get.call_count == intercom_module._SCROLL_EXPIRED_MAX_RETRIES + 1

    def test_iter_companies_walks_scroll(self):
        # `POST /companies/list` is capped at 10,000 companies (60 * 167 page
        # crosses the ceiling and Intercom 400s). The Scroll API has no ceiling:
        # the first GET carries no param, subsequent GETs feed `scroll_param`
        # back, and the walk ends when `data` comes back empty.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": [{"id": "co2"}], "scroll_param": "s2"}),
            _make_response({"data": [], "scroll_param": "s3"}),
        ]

        companies = list(_iter_companies(mock_session))

        assert [c["id"] for c in companies] == ["co1", "co2"]
        calls = mock_session.get.call_args_list
        assert calls[0].kwargs["params"] is None
        assert calls[1].kwargs["params"] == {"scroll_param": "s1"}
        assert calls[2].kwargs["params"] == {"scroll_param": "s2"}
        # Every call hits the un-capped scroll endpoint, never the 10k-capped
        # `/companies/list` (POST) path that produced the 400.
        assert all(call.args[0].endswith("/companies/scroll") for call in calls)
        assert mock_session.post.call_count == 0

    def test_iter_companies_stops_on_empty_first_page(self):
        # A workspace with no companies returns empty data on the first scroll
        # request — the walk must terminate without a second call.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [_make_response({"data": [], "scroll_param": "s1"})]

        assert list(_iter_companies(mock_session)) == []
        assert mock_session.get.call_count == 1


class TestCompaniesScrollExists:
    @pytest.mark.parametrize(
        "body,status_code,expected",
        [
            (SCROLL_EXISTS_BODY, 400, True),
            # A different 400 (e.g. a genuinely malformed request) is not the transient lock.
            ({"type": "error.list", "errors": [{"code": "parameter_invalid"}]}, 400, False),
            # Right code, wrong status — not the scroll lock.
            (SCROLL_EXISTS_BODY, 404, False),
            # No errors array at all.
            ({"type": "error.list"}, 400, False),
        ],
    )
    def test_is_scroll_exists(self, body: Any, status_code: int, expected: bool):
        assert _is_scroll_exists(_http_error(body, status_code=status_code)) is expected

    def test_is_scroll_exists_handles_non_json_body(self):
        assert _is_scroll_exists(_http_error(None, status_code=400, text="<html>bad</html>")) is False

    def test_iter_companies_retries_open_past_stale_scroll(self):
        # A scroll left open by an interrupted/concurrent sync blocks the open with
        # `400 scroll_exists` until it expires. Wait it out and retry the open
        # rather than failing the whole sync.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response(SCROLL_EXISTS_BODY, status_code=400),
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": []}),
        ]

        with mock.patch.object(intercom_module.time, "sleep") as sleep:
            companies = list(_iter_companies(mock_session))

        assert [c["id"] for c in companies] == ["co1"]
        sleep.assert_called_once_with(intercom_module._SCROLL_EXISTS_BACKOFF_SECONDS)
        # The retried open carries no scroll_param — a scroll can only restart from
        # the beginning, never resume.
        assert mock_session.get.call_args_list[1].kwargs["params"] is None

    def test_iter_companies_reraises_scroll_exists_after_max_retries(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response(SCROLL_EXISTS_BODY, status_code=400)
            for _ in range(intercom_module._SCROLL_EXISTS_MAX_RETRIES + 1)
        ]

        with mock.patch.object(intercom_module.time, "sleep"):
            with pytest.raises(HTTPError):
                list(_iter_companies(mock_session))

        assert mock_session.get.call_count == intercom_module._SCROLL_EXISTS_MAX_RETRIES + 1

    def test_iter_companies_does_not_retry_other_400(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"type": "error.list", "errors": [{"code": "parameter_invalid"}]}, status_code=400),
        ]

        with mock.patch.object(intercom_module.time, "sleep") as sleep:
            with pytest.raises(HTTPError):
                list(_iter_companies(mock_session))

        sleep.assert_not_called()
        assert mock_session.get.call_count == 1


class TestCompaniesScrollServerError:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (500, True),
            (502, True),
            (503, True),
            (504, True),
            (400, False),
            (404, False),
            (429, False),
            (200, False),
        ],
    )
    def test_is_server_error(self, status_code: int, expected: bool):
        assert _is_server_error(_http_error(None, status_code=status_code, text="boom")) is expected

    def test_iter_companies_retries_continuation_server_error(self):
        # A transient 5xx mid-walk (the observed error: 500 on
        # `/companies/scroll?scroll_param=...`) is retried inline against the same
        # scroll_param, so the walk continues without re-opening or duplicating rows.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response(None, status_code=500, text="Server Error"),
            _make_response({"data": [{"id": "co2"}], "scroll_param": "s2"}),
            _make_response({"data": []}),
        ]

        with mock.patch.object(intercom_module.time, "sleep") as sleep:
            companies = list(_iter_companies(mock_session))

        assert [c["id"] for c in companies] == ["co1", "co2"]
        sleep.assert_called_once_with(intercom_module._SCROLL_SERVER_ERROR_BACKOFF_SECONDS)
        # The retried continuation reuses the same scroll_param — the cursor only
        # advances once a page is returned.
        assert mock_session.get.call_args_list[2].kwargs["params"] == {"scroll_param": "s1"}

    def test_iter_companies_retries_open_server_error(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response(None, status_code=503, text="Service Unavailable"),
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": []}),
        ]

        with mock.patch.object(intercom_module.time, "sleep"):
            companies = list(_iter_companies(mock_session))

        assert [c["id"] for c in companies] == ["co1"]
        # The retried open carries no scroll_param.
        assert mock_session.get.call_args_list[1].kwargs["params"] is None

    def test_iter_companies_reraises_server_error_after_max_retries(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            *[
                _make_response(None, status_code=500, text="Server Error")
                for _ in range(intercom_module._SCROLL_SERVER_ERROR_MAX_RETRIES + 1)
            ],
        ]

        with mock.patch.object(intercom_module.time, "sleep"):
            with pytest.raises(HTTPError):
                list(_iter_companies(mock_session))

        # One open + every continuation attempt (initial + retries) before surfacing.
        assert mock_session.get.call_count == intercom_module._SCROLL_SERVER_ERROR_MAX_RETRIES + 2


class TestSubstreamSessionRetries:
    def test_idempotent_search_posts_are_retryable(self):
        # The substream walk reaches `/conversations/search` and `/companies/list`
        # via POST. The shared default retry policy excludes POST, so a transient
        # read timeout on those calls would propagate unretried (unlike the GETs in
        # the same walk). These POSTs are read-only/idempotent, so the session must
        # retry them on transient read timeouts and 429/5xx.
        session = _make_intercom_session("token")
        retry = cast(HTTPAdapter, session.get_adapter(INTERCOM_API_BASE)).max_retries
        allowed_methods = cast("frozenset[str]", retry.allowed_methods)

        assert {"GET", "POST"} <= set(allowed_methods)
        assert retry.total == 3
        assert 429 in (retry.status_forcelist or ())


class TestIntercomSource:
    @pytest.mark.parametrize("endpoint", list(INTERCOM_ENDPOINTS.keys()))
    def test_source_response_metadata(self, endpoint: str):
        cfg = INTERCOM_ENDPOINTS[endpoint]
        sentinel = object()

        with (
            mock.patch.object(intercom_module, "rest_api_resource", return_value=sentinel),
            mock.patch.object(intercom_module, "make_tracked_session", return_value=mock.MagicMock()),
        ):
            response = intercom_source(
                access_token="token",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
            )

        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        assert response.partition_keys == [cfg.partition_key]
        assert response.sort_mode == cfg.sort_mode

    def test_companies_routes_through_scroll_api(self):
        # `companies` must walk the un-capped Scroll API, never `POST /companies/list`
        # (capped at 10,000 — paging past it returns `400 page limit reached`). This
        # guards the dispatch: if the endpoint config reverts to a list/next_url
        # paginator it would 400 on large workspaces. The walk itself is covered by
        # `test_iter_companies_walks_scroll`.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": [], "scroll_param": "s2"}),
        ]

        with mock.patch.object(intercom_module, "make_tracked_session", return_value=mock_session):
            response = intercom_source(access_token="token", endpoint="companies", team_id=1, job_id="job-1")
            # `items()` is typed `Iterable | AsyncIterable`; the scroll path yields a sync iterator.
            companies = list(cast(Iterable[dict[str, Any]], response.items()))

        assert [c["id"] for c in companies] == ["co1"]
        urls = [call.args[0] for call in mock_session.get.call_args_list]
        assert urls and all(url.endswith("/companies/scroll") for url in urls)
