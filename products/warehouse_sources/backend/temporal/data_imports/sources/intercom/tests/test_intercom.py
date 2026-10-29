import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.driver import DriveResult
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import Script
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.intercom import (
    IntercomSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom import intercom as intercom_module
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.intercom import (
    INTERCOM_API_BASE,
    IntercomConversationCursor,
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
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source import IntercomSource


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


def _drive(
    endpoint: str, script: Script, *, resume_state: IntercomResumeConfig | None = None, **inputs: Any
) -> DriveResult:
    source = IntercomSource()
    config = IntercomSourceConfig(intercom_integration_id=456)
    # The pipeline gives every schema of a cursor source a manager, with no cursor on a first run.
    inputs.setdefault("source_cursor", SourceCursorManager(IntercomConversationCursor, None, source))
    with mock.patch.object(source, "get_oauth_integration", return_value=mock.MagicMock(access_token="token")):
        return SourceDriver(source, config).run(endpoint, script, resume_state=resume_state, **inputs)


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
        with scripted_network(always(ScriptedResponse(status=status_code, json={"type": "admin"}))) as network:
            is_valid, error = validate_credentials("token", schema_name=schema_name)

        assert {request.path for request in network.requests_log} == {"/me"}
        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None
            if status_code == 500:
                assert "HTTP 500" in error

    def test_missing_token(self):
        is_valid, error = validate_credentials("")
        assert is_valid is False
        assert error is not None and "Missing" in error

    def test_request_exception_returns_invalid(self):
        with scripted_network(always(ConnectionResetError("connection reset"))):
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
        result = _drive(endpoint, [], api_version="2.17")
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        assert response.partition_keys == [cfg.partition_key]
        assert response.sort_mode == cfg.sort_mode
        # A companies scroll expires within a minute and cannot restart mid-walk.
        assert response.supports_resume is (cfg.paginator_kind != "scroll")

    @pytest.mark.parametrize("pin", ["2.13", "2.15", "2.16", "2.17"])
    @pytest.mark.parametrize(
        "endpoint,response",
        [
            ("admins", ScriptedResponse(json={"admins": []})),
            ("conversation_parts", ScriptedResponse(json={"conversations": [], "pages": {}})),
        ],
    )
    def test_sync_requests_send_the_pinned_version(self, pin: str, endpoint: str, response: ScriptedResponse):
        result = _drive(endpoint, [response], api_version=pin)

        assert result.raised is None
        assert [request.headers["intercom-version"] for request in result.requests] == [pin]

    @pytest.mark.parametrize(
        "endpoint", [name for name, cfg in INTERCOM_ENDPOINTS.items() if cfg.api_versions is not None]
    )
    def test_endpoint_unavailable_on_the_pinned_version_raises(self, endpoint: str):
        result = _drive(endpoint, [], api_version="2.13")

        assert isinstance(result.raised, ValueError)
        assert "requires Intercom API version" in str(result.raised)


NEXT_URL = f"{INTERCOM_API_BASE}/admins/activity_logs?created_at_after=0&page=2"
SECOND_URL = f"{INTERCOM_API_BASE}/news/news_items?page=3"


def _page(selector: str, ids: list[int], next_block: Any) -> ScriptedResponse:
    return ScriptedResponse(json={selector: [{"id": i} for i in ids], "pages": {"next": next_block}})


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
        responses = [_page(selector, [i], block) for i, block in enumerate(next_blocks)]

        result = _drive(endpoint, responses)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [0, 1, 2]
        # The last page has no next page, so nothing is staged for it.
        assert result.saved_states == expected_staged

    def test_expired_search_cursor_is_cleared_before_retry(self):
        rejected = ScriptedResponse(
            status=400,
            json={"type": "error.list", "errors": [{"code": "parameter_invalid", "message": "cursor expired"}]},
        )

        result = _drive(
            "contacts",
            [rejected],
            resume_state=IntercomResumeConfig(cursor="expired", query_value=1600000000),
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

        assert isinstance(result.raised, HTTPError)
        assert result.final_state is None

    @pytest.mark.parametrize(
        "state",
        [
            IntercomResumeConfig(cursor="c5"),
            IntercomResumeConfig(next_url=NEXT_URL),
        ],
    )
    def test_search_ignores_state_it_cannot_replay(self, state: IntercomResumeConfig):
        result = _drive(
            "contacts",
            [_page("data", [1], None)],
            resume_state=state,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

        assert result.raised is None
        assert "starting_after" not in result.requests[0].json()["pagination"]
        assert result.requests[0].json()["query"]["value"] == 1700000000
        assert result.requests[0].json()["sort"] == {"field": "updated_at", "order": "ascending"}

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
        result = _drive(endpoint, [_page(selector, [5], None)], resume_state=state)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [5]
        assert len(result.requests) == 1
        if expected_params:
            assert result.urls[0].split("?", 1)[0] == expected_url
            assert {name: value[0] for name, value in result.queries[0].items()} == {
                name: str(value) for name, value in expected_params.items()
            }
        else:
            assert result.urls[0] == expected_url


def _numbered_page(ids: list[int], page: int, total_pages: int, nested: bool = False) -> ScriptedResponse:
    counts = {"page": page, "per_page": 50, "total_pages": total_pages}
    body: dict[str, Any] = {"type": "list", "data": [{"id": i} for i in ids]}
    body.update({"pages": {"type": "pages", **counts}} if nested else counts)
    return ScriptedResponse(json=body)


class TestPageNumberEndpoints:
    @pytest.mark.parametrize(
        "endpoint,per_page,nested",
        [
            ("audiences", "50", False),
            ("content_snippets", "50", False),
            ("dynamic_contents", "50", False),
            ("folders", "50", True),
            ("deleted_contacts", "150", True),
        ],
    )
    def test_fresh_run_walks_every_page_and_stops_at_total_pages(self, endpoint: str, per_page: str, nested: bool):
        responses = [_numbered_page([1], 1, 2, nested), _numbered_page([2], 2, 2, nested)]

        result = _drive(endpoint, responses)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        # The last page is known from `total_pages`, so no trailing empty-page request goes out.
        assert result.params("per_page") == [per_page, per_page]
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [IntercomResumeConfig(page=2)]

    def test_resumed_run_starts_at_the_saved_page(self):
        result = _drive("audiences", [_numbered_page([7], 3, 3)], resume_state=IntercomResumeConfig(page=3))

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert len(result.requests) == 1
        assert result.params("per_page") == ["50"]
        assert result.params("page") == ["3"]


def _segments_script(scroll_ids: list[str], segments: dict[str, Any]) -> Script:
    responses = {
        "/companies/scroll": [
            ScriptedResponse(json={"data": [{"id": cid} for cid in scroll_ids], "scroll_param": "s1"}),
            ScriptedResponse(json={"data": []}),
        ],
        **{
            f"/companies/{cid}/segments": [
                ScriptedResponse(status=404) if body is None else ScriptedResponse(json=body)
            ]
            for cid, body in segments.items()
        },
    }
    return route(responses)


class TestExpiredSubstreamCursor:
    def test_expired_conversation_search_cursor_is_cleared(self):
        result = _drive(
            "conversation_parts",
            [
                ScriptedResponse(
                    status=400,
                    json={"type": "error.list", "errors": [{"code": "parameter_invalid", "message": "cursor expired"}]},
                )
            ],
            resume_state=IntercomResumeConfig(cursor="expired", query_value=1600000000),
            incremental_field="updated_at",
        )

        assert isinstance(result.raised, HTTPError)
        assert result.final_state is None


class TestResumableCompanySegments:
    def test_fresh_run_stages_each_company_in_sorted_order(self):
        # co2 has no segments and co4 was deleted: both still move the cursor and reach a safe
        # point, because a long run of empty companies must still hand off at shutdown.
        result = _drive(
            "company_segments",
            _segments_script(
                ["co3", "co1", "co4", "co2"],
                {
                    "co1": {"data": [{"id": "s1"}]},
                    "co2": {"data": []},
                    "co3": {"data": [{"id": "s3"}, {"id": "s4"}]},
                    "co4": None,
                },
            ),
        )

        assert result.raised is None
        assert [(s["company_id"], s["id"]) for s in result.rows] == [
            ("co1", "s1"),
            ("co3", "s3"),
            ("co3", "s4"),
        ]
        assert result.saved_states == [
            IntercomResumeConfig(last_company_id=cid) for cid in ["co1", "co2", "co3", "co4"]
        ]
        assert result.final_state == IntercomResumeConfig(last_company_id="co4")

    def test_resumed_run_skips_completed_companies(self):
        result = _drive(
            "company_segments",
            _segments_script(
                ["co3", "co1", "co2"],
                {"co1": {"data": [{"id": "s1"}]}, "co2": {"data": [{"id": "s2"}]}, "co3": {"data": [{"id": "s3"}]}},
            ),
            resume_state=IntercomResumeConfig(last_company_id="co2"),
        )

        assert result.raised is None
        assert [s["id"] for s in result.rows] == ["s3"]
        assert [path for path in result.paths if path.endswith("/segments")] == ["/companies/co3/segments"]


def _conversation_page(ids: list[str], next_cursor: str | None) -> ScriptedResponse:
    next_block = {"starting_after": next_cursor} if next_cursor else None
    return ScriptedResponse(json={"conversations": [{"id": cid} for cid in ids], "pages": {"next": next_block}})


def _parts(*ids: str) -> ScriptedResponse:
    return ScriptedResponse(json={"conversation_parts": {"conversation_parts": [{"id": pid} for pid in ids]}})


class TestResumableConversationParts:
    def test_fresh_run_stages_after_each_conversation_and_page(self):
        result = _drive(
            "conversation_parts",
            [
                _conversation_page(["c1", "c2"], "p2"),
                _parts("a", "b"),
                _parts(),
                _conversation_page(["c3"], None),
                _parts("c"),
            ],
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert [p["id"] for p in result.rows] == ["a", "b", "c"]
        assert result.saved_states == [
            IntercomResumeConfig(query_value=0, completed_conversation_ids=["c1"]),
            IntercomResumeConfig(query_value=0, completed_conversation_ids=["c1", "c2"]),
            IntercomResumeConfig(cursor="p2", query_value=0),
            IntercomResumeConfig(cursor="p2", query_value=0, completed_conversation_ids=["c3"]),
        ]
        assert result.final_state == IntercomResumeConfig(cursor="p2", query_value=0, completed_conversation_ids=["c3"])

    def test_resumed_run_replays_the_saved_page_and_skips_completed_conversations(self):
        result = _drive(
            "conversation_parts",
            [_conversation_page(["c3", "c4"], None), _parts("d")],
            resume_state=IntercomResumeConfig(cursor="p2", query_value=1600000000, completed_conversation_ids=["c3"]),
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

        assert result.raised is None
        assert [(p["conversation_id"], p["id"]) for p in result.rows] == [("c4", "d")]
        body = result.requests[0].json()
        assert body["pagination"]["starting_after"] == "p2"
        assert body["query"]["value"] == 1600000000
        assert result.paths == ["/conversations/search", "/conversations/c4"]

    def test_hitl_events_walk_parents_from_the_source_cursor_and_advance_it(self):
        cursor_manager = SourceCursorManager(
            IntercomConversationCursor, IntercomConversationCursor(updated_at=1700000000), IntercomSource()
        )
        rounds = [
            {"hitl_cycle_id": "h1", "event_type": "fin_consultation_started", "created_at": 1700000050, "data": {}},
            *(
                {
                    "hitl_cycle_id": "h1",
                    "event_type": "fin_teammate_input_received",
                    "created_at": 1700000060,
                    "data": {"round_index": i},
                }
                for i in (1, 2)
            ),
        ]
        result = _drive(
            "conversation_hitl_events",
            [
                ScriptedResponse(
                    json={
                        "conversations": [
                            {"id": "c1", "updated_at": 1700000100},
                            {"id": "c2", "updated_at": 1700000200},
                        ],
                        "pages": {"next": None},
                    }
                ),
                ScriptedResponse(json={"type": "list", "data": rounds}),
                ScriptedResponse(json={"type": "list", "data": []}),
            ],
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value=1700000060,
            source_cursor=cursor_manager,
        )

        assert result.raised is None
        assert [(e["conversation_id"], e["event_type"], e["round_index"]) for e in result.rows] == [
            ("c1", "fin_consultation_started", 0),
            ("c1", "fin_teammate_input_received", 1),
            ("c1", "fin_teammate_input_received", 2),
        ]
        assert result.requests[0].json()["query"] == {"field": "updated_at", "operator": ">", "value": 1700000000}
        assert result.paths == [
            "/conversations/search",
            "/conversations/c1/hitl_events",
            "/conversations/c2/hitl_events",
        ]
        # A conversation with no events still moves the cursor, so the next run skips it.
        assert cursor_manager.staged == IntercomConversationCursor(updated_at=1700000200)
