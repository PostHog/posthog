import json
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mem0 import mem0 as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0 import (
    _MATCH_ALL_FILTER,
    Mem0ResumeConfig,
    mem0_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_BASE_URL,
    MEMORIES_ENDPOINT,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mem0 module.
MEM0_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0.make_tracked_session"


def _response(
    results: list[dict[str, Any]] | None = None, *, status: int = 200, next_url: str | None = None
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{MEM0_BASE_URL}/v3/memories/"
    body: Any = {"count": len(results or []), "next": next_url, "previous": None, "results": results or []}
    resp._content = json.dumps(body).encode()
    return resp


def _raw_response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{MEM0_BASE_URL}/v1/entities/"
    resp._content = json.dumps(body).encode()
    return resp


def _manager(resume: Mem0ResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; capture each request AT PREPARE TIME as a real PreparedRequest.

    Preparing with a real session applies the framework auth and encodes params/json exactly as
    they'd go on the wire, so tests can assert the outgoing URL, Authorization header, and body.
    """
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses: list[Response], manager: mock.MagicMock, **kwargs: Any) -> tuple[list, list]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        prepared = _wire(session, responses)
        rows = _rows(
            mem0_source("m0-test", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
        )
    return rows, prepared


def _query(prepared: requests.PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(cast("str", prepared.url)).query)


def _body(prepared: requests.PreparedRequest) -> Any:
    return json.loads(cast("str", prepared.body))


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False)])
    @mock.patch(MEM0_SESSION_PATCH)
    def test_maps_status_code_to_validity(self, status_code, expected, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("m0-test") is expected

    @mock.patch(MEM0_SESSION_PATCH)
    def test_network_error_is_invalid_not_raised(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("m0-test") is False

    @mock.patch(MEM0_SESSION_PATCH)
    def test_probes_the_ping_endpoint_with_token_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("m0-test")

        _args, kwargs = mock_session.return_value.get.call_args
        assert mock_session.return_value.get.call_args.args[0] == f"{MEM0_BASE_URL}/v1/ping/"
        assert kwargs["headers"]["Authorization"] == "Token m0-test"


class TestMemoriesRows:
    def test_yields_every_page_and_terminates_on_null_next(self):
        next_url = f"{MEM0_BASE_URL}/v3/memories/?page=2&page_size=100"
        rows, prepared = _run(
            MEMORIES_ENDPOINT,
            [_response([{"id": "m1"}, {"id": "m2"}], next_url=next_url), _response([{"id": "m3"}], next_url=None)],
            _manager(),
        )

        assert rows == [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        assert _query(prepared[0])["page"] == ["1"]
        assert "page=2" in prepared[1].url
        assert all(_query(p).get("page_size") == ["100"] for p in prepared)

    def test_posts_with_token_auth_header(self):
        _rows_, prepared = _run(MEMORIES_ENDPOINT, [_response([{"id": "m1"}], next_url=None)], _manager())

        assert prepared[0].method == "POST"
        assert prepared[0].headers["Authorization"] == "Token m0-test"

    def test_full_sync_sends_wildcard_filter_over_every_entity_type(self):
        # A bare {"user_id": "*"} filter would silently drop memories scoped only to an agent,
        # app, or run; the request must OR the wildcard across all four entity ids.
        _rows_, prepared = _run(MEMORIES_ENDPOINT, [_response([], next_url=None)], _manager())

        body = _body(prepared[0])
        assert body == {"filters": _MATCH_ALL_FILTER}
        assert {"agent_id": "*"} in body["filters"]["OR"]

    def test_incremental_sync_filters_on_the_users_chosen_field(self):
        _rows_, prepared = _run(
            MEMORIES_ENDPOINT,
            [_response([], next_url=None)],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 1, 12, 30, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert _body(prepared[0]) == {"filters": {"AND": [_MATCH_ALL_FILTER, {"created_at": {"gte": "2026-07-01"}}]}}

    def test_saves_resume_state_only_after_yielding_and_only_when_pages_remain(self):
        next_url = f"{MEM0_BASE_URL}/v3/memories/?page=2&page_size=100"
        manager = _manager()
        _run(
            MEMORIES_ENDPOINT,
            [_response([{"id": "m1"}], next_url=next_url), _response([{"id": "m2"}], next_url=None)],
            manager,
        )

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == Mem0ResumeConfig(
            endpoint=MEMORIES_ENDPOINT, next_url=next_url, cutoff=None
        )

    def test_resumes_from_saved_next_url_and_pins_the_original_cutoff(self):
        # The saved cutoff (not a freshly computed one) must drive the filter on resume, otherwise
        # the resumed run paginates a different server-side result set than the pages it already saw.
        saved_url = f"{MEM0_BASE_URL}/v3/memories/?page=3&page_size=100"
        manager = _manager(Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, next_url=saved_url, cutoff="2026-06-01"))

        _rows_, prepared = _run(
            MEMORIES_ENDPOINT,
            [_response([], next_url=None)],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 10, tzinfo=UTC),
        )

        assert "page=3" in prepared[0].url
        assert _body(prepared[0]) == {"filters": {"AND": [_MATCH_ALL_FILTER, {"updated_at": {"gte": "2026-06-01"}}]}}

    def test_ignores_resume_state_saved_by_a_different_endpoint(self):
        manager = _manager(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=f"{MEM0_BASE_URL}/v1/events/?page=9"))

        _rows_, prepared = _run(MEMORIES_ENDPOINT, [_response([], next_url=None)], manager)

        assert _query(prepared[0])["page"] == ["1"]


class TestCutoffFormatting:
    @parameterized.expand(
        [
            (datetime(2026, 7, 1, 23, 59, tzinfo=UTC), "2026-07-01"),
            (datetime(2026, 7, 1, 12, 0), "2026-07-01"),  # naive treated as UTC
            (date(2026, 7, 1), "2026-07-01"),
            ("2026-07-01", "2026-07-01"),
            (None, None),
        ]
    )
    def test_formats_cursor_as_date_string(self, value, expected):
        assert api_client._format_cutoff(value) == expected


class TestEntitiesRows:
    def test_yields_the_bare_array_response(self):
        rows, prepared = _run(ENTITIES_ENDPOINT, [_raw_response([{"id": "alex", "type": "user"}])], _manager())

        assert rows == [{"id": "alex", "type": "user"}]
        assert prepared[0].method == "GET"
        assert urlsplit(prepared[0].url).path == "/v1/entities/"

    def test_tolerates_an_enveloped_response(self):
        rows, _prepared = _run(ENTITIES_ENDPOINT, [_raw_response({"results": [{"id": "alex"}]})], _manager())

        assert rows == [{"id": "alex"}]

    @parameterized.expand(
        [
            ("org_only", "org_1", None, {"org_id": ["org_1"]}),
            ("project_only", None, "proj_1", {"project_id": ["proj_1"]}),
            ("both", "org_1", "proj_1", {"org_id": ["org_1"], "project_id": ["proj_1"]}),
        ]
    )
    def test_scopes_listing_with_org_and_project_params(self, _name, org_id, project_id, expected_query):
        _rows_, prepared = _run(
            ENTITIES_ENDPOINT, [_raw_response([])], _manager(), org_id=org_id, project_id=project_id
        )

        assert _query(prepared[0]) == expected_query


class TestEventsRows:
    def test_follows_next_urls_and_checkpoints_after_each_yield(self):
        next_url = f"{MEM0_BASE_URL}/v1/events/?page=2"
        manager = _manager()
        rows, prepared = _run(
            EVENTS_ENDPOINT,
            [_response([{"id": "e1"}], next_url=next_url), _response([{"id": "e2"}], next_url=None)],
            manager,
        )

        assert rows == [{"id": "e1"}, {"id": "e2"}]
        assert prepared[1].url == next_url
        manager.save_state.assert_called_once_with(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=next_url))

    def test_follows_relative_next_urls(self):
        # Mem0's /v1/events/ envelope returns a relative `next` link; it must resolve against the
        # API origin rather than be rejected as off-origin.
        absolute_next = f"{MEM0_BASE_URL}/v1/events/?page=2"
        manager = _manager()
        rows, prepared = _run(
            EVENTS_ENDPOINT,
            [_response([{"id": "e1"}], next_url="/v1/events/?page=2"), _response([{"id": "e2"}], next_url=None)],
            manager,
        )

        assert rows == [{"id": "e1"}, {"id": "e2"}]
        assert prepared[1].url == absolute_next
        manager.save_state.assert_called_once_with(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=absolute_next))

    def test_resumes_from_the_saved_next_url(self):
        saved_url = f"{MEM0_BASE_URL}/v1/events/?page=5"
        manager = _manager(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=saved_url))

        _rows_, prepared = _run(EVENTS_ENDPOINT, [_response([], next_url=None)], manager)

        assert prepared[0].url == saved_url

    @parameterized.expand(
        [
            ("absolute", "https://evil.example.com/v1/events/?page=2"),
            ("scheme_relative", "//evil.example.com/v1/events/?page=2"),
            ("non_https", "http://api.mem0.ai/v1/events/?page=2"),
            ("lookalike_host", "https://api.mem0.ai.evil.example.com/v1/events/?page=2"),
        ]
    )
    def test_refuses_to_follow_off_origin_next_links(self, _name, next_url):
        # The session carries the API key; a tampered `next` link must never receive a credentialed
        # request or be persisted as resume state.
        manager = _manager()

        with pytest.raises(ValueError):
            _run(EVENTS_ENDPOINT, [_response([{"id": "e1"}], next_url=next_url)], manager)

        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("absolute", "https://evil.example.com/v1/events/?page=5"),
            ("non_https", "http://api.mem0.ai/v1/events/?page=5"),
        ]
    )
    def test_refuses_to_resume_from_an_off_origin_saved_url(self, _name, saved_url):
        manager = _manager(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=saved_url))

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, [_response([], next_url=None)])
            with pytest.raises(ValueError):
                _rows(mem0_source("m0-test", EVENTS_ENDPOINT, team_id=1, job_id="j", resumable_source_manager=manager))

            session.send.assert_not_called()


class TestFetchRetry:
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    def test_retries_rate_limits_then_succeeds(self, _sleep):
        rows, prepared = _run(
            MEMORIES_ENDPOINT,
            [_response([], status=429), _response([{"id": "m1"}], next_url=None)],
            _manager(),
        )

        assert rows == [{"id": "m1"}]
        assert len(prepared) == 2

    def test_auth_errors_raise_immediately_without_retry(self):
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            prepared = _wire(session, [_response([], status=401)])
            with pytest.raises(requests.HTTPError):
                _rows(
                    mem0_source(
                        "m0-test", MEMORIES_ENDPOINT, team_id=1, job_id="j", resumable_source_manager=_manager()
                    )
                )

        assert len(prepared) == 1


class TestMem0SourceResponse:
    def test_memories_response_merges_on_id_and_partitions_on_stable_created_at(self):
        response = mem0_source("m0-test", MEMORIES_ENDPOINT, team_id=1, job_id="j", resumable_source_manager=_manager())

        assert response.name == MEMORIES_ENDPOINT
        assert response.primary_keys == ["id"]
        # The list endpoint has no sort parameter, so ordering is undefined; "desc" defers the
        # incremental watermark commit to successful end of run.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_entities_response_has_no_partitioning(self):
        response = mem0_source("m0-test", ENTITIES_ENDPOINT, team_id=1, job_id="j", resumable_source_manager=_manager())

        assert response.partition_mode is None
        assert response.partition_keys is None
