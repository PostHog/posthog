import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom import intercom as intercom_module
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.intercom import (
    INTERCOM_API_BASE,
    IntercomPagesPaginator,
    IntercomResumeConfig,
    IntercomSearchPaginator,
    _build_paginator,
    _company_segments_generator,
    _conversation_parts_generator,
    _drain_company_ids,
    _intercom_get,
    _is_scroll_exists,
    _iter_companies,
    _rate_limit_backoff_seconds,
    _substream_items,
    _to_unix_seconds,
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


def _manager(state: IntercomResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


def _staged(manager: mock.MagicMock) -> list[IntercomResumeConfig]:
    return [call.args[0] for call in manager.save_state.call_args_list]


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
    def test_update_state_handles_bad_json(self):
        paginator = IntercomSearchPaginator()
        response = _make_response(None, text="not json")

        paginator.update_state(response)

        assert paginator.has_next_page is False


class TestBuildPaginator:
    @pytest.mark.parametrize(
        "kind,expected_type",
        [
            ("search", IntercomSearchPaginator),
            ("cursor", JSONResponseCursorPaginator),
            ("next_url", JSONResponsePaginator),
            ("pages", IntercomPagesPaginator),
            ("page_number", PageNumberPaginator),
            ("single", SinglePagePaginator),
        ],
    )
    def test_paginator_per_kind(self, kind: str, expected_type: type):
        cfg = mock.MagicMock()
        cfg.paginator_kind = kind
        assert isinstance(_build_paginator(cfg), expected_type)


class TestPagesPaginator:
    def test_terminates_on_non_json_body(self):
        paginator = IntercomPagesPaginator()
        paginator.update_state(_make_response(None, text="<html>bad gateway</html>"))

        assert paginator.has_next_page is False

    def test_stops_when_the_cursor_stops_advancing(self):
        # A repeated cursor would refetch the same page until the Temporal activity
        # times out, which for these tables is a very long time to spend on one page.
        paginator = IntercomPagesPaginator()
        body = {"pages": {"next": {"starting_after": "cursor-1"}}}

        paginator.update_state(_make_response(body))
        assert paginator.has_next_page is True

        paginator.update_state(_make_response(body))
        assert paginator.has_next_page is False


class TestGetResource:
    @pytest.mark.parametrize(
        "should_use_incremental,last_value,expected_disposition,expected_since",
        [
            # Macro timestamps are ISO strings, so the watermark arrives as a datetime.
            (
                True,
                datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
                {"disposition": "merge", "strategy": "upsert"},
                1700000000,
            ),
            (False, None, "replace", 0),
        ],
    )
    def test_macros_send_the_watermark_as_unix_seconds(
        self, should_use_incremental: bool, last_value: Any, expected_disposition: Any, expected_since: int
    ):
        resource = get_resource(
            "macros",
            should_use_incremental_field=should_use_incremental,
            incremental_field="updated_at" if should_use_incremental else None,
            db_incremental_field_last_value=last_value,
        )

        assert _endpoint(resource)["params"]["updated_since"] == expected_since
        assert resource["write_disposition"] == expected_disposition


@pytest.mark.parametrize(
    "value,expected",
    [
        (1700000000, 1700000000),
        ("1700000000", 1700000000),
        (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
        (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
        ("2023-11-14T22:13:20.000Z", 1700000000),
    ],
)
def test_to_unix_seconds(value: Any, expected: int):
    assert _to_unix_seconds(value) == expected


class TestNoSourceLevelTypeCoercion:
    # Type flips (Intercom returning a field as an int on some rows and a string on others)
    # are stabilized generically when batches are built, not by naming fields per endpoint.
    # These guard against a per-field allowlist creeping back in.

    def test_unknown_substream_endpoint_raises(self):
        # Adding a substream endpoint config without wiring it into _substream_items
        # must fail loud, not silently yield nothing.
        with pytest.raises(ValueError):
            list(_substream_items(mock.MagicMock(), "not_a_real_endpoint", None, None))


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


class TestCompaniesScrollExists:
    def test_is_scroll_exists_handles_non_json_body(self):
        assert _is_scroll_exists(_http_error(None, status_code=400, text="<html>bad</html>")) is False

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


class TestRateLimitRetry:
    @pytest.mark.parametrize("raw", [None, "not-a-number"])
    def test_backoff_falls_back_without_usable_retry_after(self, raw: str | None):
        resp = _make_response(None, status_code=429, text="Too Many Requests")
        if raw is not None:
            resp.headers["Retry-After"] = raw
        assert _rate_limit_backoff_seconds(resp, default=10.0) == 10.0

    def test_company_segments_retries_rate_limited_segment_fetch(self):
        # The observed failure: a burst of per-company `/companies/{id}/segments`
        # fetches trips Intercom's rate limit and 429s. Riding out the window inline
        # lets the walk continue instead of failing the whole sync. Scroll is drained
        # first (two GETs), then the segment fetch 429s once and succeeds on retry.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co1"}], "scroll_param": "s1"}),
            _make_response({"data": []}),
            _make_response(None, status_code=429, text="Too Many Requests"),
            _make_response({"data": [{"id": "seg1"}]}),
        ]

        with mock.patch.object(intercom_module.time, "sleep") as sleep:
            segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["seg1"]
        assert segments[0]["company_id"] == "co1"
        sleep.assert_called_once_with(intercom_module._RATE_LIMIT_BACKOFF_SECONDS)

    def test_intercom_get_reraises_rate_limit_after_max_retries(self):
        # A persistent 429 must surface after the bounded retries rather than
        # looping forever, so Temporal can retry the activity.
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            _make_response(None, status_code=429, text="Too Many Requests")
            for _ in range(intercom_module._RATE_LIMIT_MAX_RETRIES + 1)
        ]

        with mock.patch.object(intercom_module.time, "sleep"):
            with pytest.raises(HTTPError):
                _intercom_get(mock_session, "/companies/co1/segments")

        assert mock_session.get.call_count == intercom_module._RATE_LIMIT_MAX_RETRIES + 1


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
                api_version="2.16",
                resumable_source_manager=_manager(),
            )

        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        assert response.partition_keys == [cfg.partition_key]
        assert response.sort_mode == cfg.sort_mode
        # A companies scroll expires within a minute and cannot restart mid-walk.
        assert response.supports_resume is (cfg.paginator_kind != "scroll")

    @pytest.mark.parametrize(
        "endpoint", [name for name, cfg in INTERCOM_ENDPOINTS.items() if cfg.api_versions is not None]
    )
    def test_endpoint_unavailable_on_the_pinned_version_raises(self, endpoint: str):
        with pytest.raises(ValueError, match="requires Intercom API version"):
            intercom_source(
                access_token="token",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                api_version="2.13",
                resumable_source_manager=_manager(),
            )


REST_CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
NEXT_URL = f"{INTERCOM_API_BASE}/admins/activity_logs?created_at_after=0&page=2"
SECOND_URL = f"{INTERCOM_API_BASE}/news/news_items?page=3"


def _wire_rest_session(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    # The client mutates one Request across pages, so copy what each send carries.
    session.headers = {}
    sent: list[dict[str, Any]] = []

    def prepare(request: Any) -> mock.MagicMock:
        sent.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "json": json.loads(json.dumps(request.json)) if request.json is not None else None,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = prepare
    session.send.side_effect = responses
    return sent


def _run_rest(
    endpoint: str, manager: mock.MagicMock, responses: list[Response], **kwargs: Any
) -> tuple[list[Any], list[dict[str, Any]]]:
    with mock.patch(REST_CLIENT_SESSION_PATCH) as make_session:
        sent = _wire_rest_session(make_session.return_value, responses)
        response = intercom_source(
            access_token="token",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            api_version="2.16",
            resumable_source_manager=manager,
            **kwargs,
        )
        rows = [row["id"] for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]
    return rows, sent


def _page(selector: str, ids: list[int], next_block: Any) -> Response:
    return _make_response({selector: [{"id": i} for i in ids], "pages": {"next": next_block}})


class TestResumableRestEndpoints:
    @pytest.mark.parametrize(
        "endpoint,selector,next_blocks,expected_staged",
        [
            (
                "contacts",
                "data",
                [{"starting_after": "c2"}, {"starting_after": "c3"}, None],
                [IntercomResumeConfig(cursor="c2", query_value=0), IntercomResumeConfig(cursor="c3", query_value=0)],
            ),
            (
                "activity_logs",
                "activity_logs",
                [NEXT_URL, f"{NEXT_URL}3", None],
                [IntercomResumeConfig(next_url=NEXT_URL), IntercomResumeConfig(next_url=f"{NEXT_URL}3")],
            ),
            (
                "collections",
                "data",
                [{"starting_after": "c2"}, {"starting_after": "c3"}, None],
                [IntercomResumeConfig(cursor="c2"), IntercomResumeConfig(cursor="c3")],
            ),
            (
                "news_items",
                "data",
                [f"{INTERCOM_API_BASE}/news/news_items?page=2", SECOND_URL, None],
                [
                    IntercomResumeConfig(next_url=f"{INTERCOM_API_BASE}/news/news_items?page=2"),
                    IntercomResumeConfig(next_url=SECOND_URL),
                ],
            ),
        ],
    )
    def test_fresh_run_stages_the_next_page_after_each_page(
        self, endpoint: str, selector: str, next_blocks: list[Any], expected_staged: list[IntercomResumeConfig]
    ):
        manager = _manager()
        responses = [_page(selector, [i], block) for i, block in enumerate(next_blocks)]

        rows, _ = _run_rest(endpoint, manager, responses)

        assert rows == [0, 1, 2]
        # The last page has no next page, so nothing is staged for it.
        assert _staged(manager) == expected_staged

    def test_expired_search_cursor_is_cleared_before_retry(self):
        manager = _manager(IntercomResumeConfig(cursor="expired", query_value=1600000000))
        rejected = _make_response(
            {"type": "error.list", "errors": [{"code": "parameter_invalid", "message": "cursor expired"}]},
            status_code=400,
        )

        with pytest.raises(HTTPError):
            _run_rest(
                "contacts",
                manager,
                [rejected],
                should_use_incremental_field=True,
                incremental_field="updated_at",
                db_incremental_field_last_value="1700000000",
            )

        manager.clear_state.assert_called_once_with()

    @pytest.mark.parametrize(
        "state",
        [
            IntercomResumeConfig(cursor="c5"),
            IntercomResumeConfig(next_url=NEXT_URL),
        ],
    )
    def test_search_ignores_state_it_cannot_replay(self, state: IntercomResumeConfig):
        manager = _manager(state)

        _, sent = _run_rest(
            "contacts",
            manager,
            [_page("data", [1], None)],
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

        assert "starting_after" not in sent[0]["json"]["pagination"]
        assert sent[0]["json"]["query"]["value"] == 1700000000

    @pytest.mark.parametrize(
        "endpoint,selector,state,expected_url,expected_params",
        [
            (
                "activity_logs",
                "activity_logs",
                IntercomResumeConfig(next_url=NEXT_URL),
                NEXT_URL,
                {},
            ),
            (
                "collections",
                "data",
                IntercomResumeConfig(cursor="c5"),
                f"{INTERCOM_API_BASE}/help_center/collections",
                {"per_page": 150, "starting_after": "c5"},
            ),
            (
                "news_items",
                "data",
                IntercomResumeConfig(next_url=SECOND_URL),
                SECOND_URL,
                {},
            ),
        ],
    )
    def test_resumed_list_starts_at_the_saved_page(
        self,
        endpoint: str,
        selector: str,
        state: IntercomResumeConfig,
        expected_url: str,
        expected_params: dict[str, Any],
    ):
        rows, sent = _run_rest(endpoint, _manager(state), [_page(selector, [5], None)])

        assert rows == [5]
        assert len(sent) == 1
        assert sent[0]["url"] == expected_url
        assert sent[0]["params"] == expected_params


def _numbered_page(ids: list[int], page: int, total_pages: int) -> Response:
    return _make_response(
        {"type": "list", "data": [{"id": i} for i in ids], "page": page, "per_page": 50, "total_pages": total_pages}
    )


class TestPageNumberEndpoints:
    @pytest.mark.parametrize("endpoint", ["audiences", "content_snippets"])
    def test_fresh_run_walks_every_page_and_stops_at_total_pages(self, endpoint: str):
        manager = _manager()
        responses = [_numbered_page([1], 1, 2), _numbered_page([2], 2, 2)]

        rows, sent = _run_rest(endpoint, manager, responses)

        assert rows == [1, 2]
        # The last page is known from `total_pages`, so no trailing empty-page request goes out.
        assert [req["params"] for req in sent] == [{"per_page": 50, "page": 1}, {"per_page": 50, "page": 2}]
        assert _staged(manager) == [IntercomResumeConfig(page=2)]

    def test_resumed_run_starts_at_the_saved_page(self):
        rows, sent = _run_rest("audiences", _manager(IntercomResumeConfig(page=3)), [_numbered_page([7], 3, 3)])

        assert rows == [7]
        assert len(sent) == 1
        assert sent[0]["params"] == {"per_page": 50, "page": 3}


def _segments_session(scroll_ids: list[str], segments: dict[str, Any]) -> mock.MagicMock:
    responses: dict[str, Any] = {f"/companies/{cid}/segments": body for cid, body in segments.items()}

    def get(url: str, params: Any = None, timeout: int = 30) -> Response:
        if url.endswith("/companies/scroll"):
            if params is None:
                return _make_response({"data": [{"id": cid} for cid in scroll_ids], "scroll_param": "s1"})
            return _make_response({"data": []})
        body = responses[url.removeprefix(INTERCOM_API_BASE)]
        if body is None:
            return _make_response(None, status_code=404, text="Not Found")
        return _make_response(body)

    session = mock.MagicMock()
    session.get.side_effect = get
    return session


def _segment_urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list if call.args[0].endswith("/segments")]


class TestExpiredSubstreamCursor:
    def test_expired_conversation_search_cursor_is_cleared(self):
        manager = _manager(IntercomResumeConfig(cursor="expired", query_value=1600000000))
        session = mock.MagicMock()
        session.post.return_value = _make_response(
            {"type": "error.list", "errors": [{"code": "parameter_invalid", "message": "cursor expired"}]},
            status_code=400,
        )

        with mock.patch.object(intercom_module, "_make_intercom_session", return_value=session):
            response = intercom_source(
                access_token="token",
                endpoint="conversation_parts",
                team_id=1,
                job_id="job-1",
                api_version="2.16",
                resumable_source_manager=manager,
                incremental_field="updated_at",
            )
            with pytest.raises(HTTPError):
                list(cast(Iterable[Any], response.items()))

        manager.clear_state.assert_called_once_with()


class TestResumableCompanySegments:
    def test_fresh_run_stages_each_company_in_sorted_order(self):
        # co2 has no segments and co4 was deleted: both still move the cursor and reach a safe
        # point, because a long run of empty companies must still hand off at shutdown.
        session = _segments_session(
            ["co3", "co1", "co4", "co2"],
            {
                "co1": {"data": [{"id": "s1"}]},
                "co2": {"data": []},
                "co3": {"data": [{"id": "s3"}, {"id": "s4"}]},
                "co4": None,
            },
        )
        manager = _manager()

        segments = list(_company_segments_generator(session, manager))

        assert [(s["company_id"], s["id"]) for s in segments] == [("co1", "s1"), ("co3", "s3"), ("co3", "s4")]
        assert _staged(manager) == [IntercomResumeConfig(last_company_id=cid) for cid in ["co1", "co2", "co3", "co4"]]
        # One safe point per drained scroll page, plus one per company.
        assert manager.safe_point.call_count == 1 + 4

    def test_resumed_run_skips_completed_companies(self):
        session = _segments_session(
            ["co3", "co1", "co2"],
            {"co1": {"data": [{"id": "s1"}]}, "co2": {"data": [{"id": "s2"}]}, "co3": {"data": [{"id": "s3"}]}},
        )
        manager = _manager(IntercomResumeConfig(last_company_id="co2"))

        segments = list(_company_segments_generator(session, manager))

        assert [s["id"] for s in segments] == ["s3"]
        assert _segment_urls(session) == [f"{INTERCOM_API_BASE}/companies/co3/segments"]


def _conversation_page(ids: list[str], next_cursor: str | None) -> Response:
    next_block = {"starting_after": next_cursor} if next_cursor else None
    return _make_response({"conversations": [{"id": cid} for cid in ids], "pages": {"next": next_block}})


def _parts(*ids: str) -> Response:
    return _make_response({"conversation_parts": {"conversation_parts": [{"id": pid} for pid in ids]}})


class TestResumableConversationParts:
    def test_fresh_run_stages_after_each_conversation_and_page(self):
        session = mock.MagicMock()
        session.post.side_effect = [_conversation_page(["c1", "c2"], "p2"), _conversation_page(["c3"], None)]
        session.get.side_effect = [_parts("a", "b"), _parts(), _parts("c")]
        manager = _manager()

        parts = list(_conversation_parts_generator(session, "updated_at", None, manager))

        assert [p["id"] for p in parts] == ["a", "b", "c"]
        assert _staged(manager) == [
            IntercomResumeConfig(query_value=0, completed_conversation_ids=["c1"]),
            IntercomResumeConfig(query_value=0, completed_conversation_ids=["c1", "c2"]),
            IntercomResumeConfig(cursor="p2", query_value=0),
            IntercomResumeConfig(cursor="p2", query_value=0, completed_conversation_ids=["c3"]),
        ]
        assert manager.safe_point.call_count == 4

    def test_resumed_run_replays_the_saved_page_and_skips_completed_conversations(self):
        session = mock.MagicMock()
        session.post.side_effect = [_conversation_page(["c3", "c4"], None)]
        session.get.side_effect = [_parts("d")]
        manager = _manager(IntercomResumeConfig(cursor="p2", query_value=1600000000, completed_conversation_ids=["c3"]))

        parts = list(_conversation_parts_generator(session, "updated_at", "1700000000", manager))

        assert [(p["conversation_id"], p["id"]) for p in parts] == [("c4", "d")]
        body = session.post.call_args_list[0].kwargs["json"]
        assert body["pagination"]["starting_after"] == "p2"
        assert body["query"]["value"] == 1600000000
        assert [call.args[0] for call in session.get.call_args_list] == [f"{INTERCOM_API_BASE}/conversations/c4"]
