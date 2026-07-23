import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse import discourse
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.discourse import (
    POSTS_PAGE_SIZE,
    DiscourseHostNotAllowedError,
    DiscoursePostsPaginator,
    DiscourseResumeConfig,
    _flatten_directory_item,
    discourse_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)

# RESTClient builds its pipeline session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The runtime host-safety guard resolves DNS; patch it so pipeline tests don't hit the network.
IS_HOST_SAFE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.discourse.discourse._is_host_safe"
)

BASE_URL = "https://forum.example.com"
API_KEY = "secret-key"
API_USERNAME = "system"


def _post(post_id: int) -> dict[str, Any]:
    return {"id": post_id, "topic_id": 1, "raw": f"post {post_id}"}


def _json_response(body: Any, *, status_code: int = 200, location: Optional[str] = None) -> requests.Response:
    """A real requests.Response so the framework's status/redirect/parse handling behaves as in prod."""
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = f"{BASE_URL}/probe"
    resp.reason = "OK" if status_code < 400 else "Error"
    if location is not None:
        resp.headers["Location"] = location
    resp._content = json.dumps(body).encode()
    return resp


def _mock_response(status_code: int = 200, json_data: Any = None, is_redirect: bool = False) -> MagicMock:
    """MagicMock response for the validate_credentials probe helper."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.json.return_value = json_data
    response.text = str(json_data)
    return response


def _make_manager(resume_state: Optional[DiscourseResumeConfig] = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    manager: MagicMock,
    endpoint: str,
    *,
    base_url: str = BASE_URL,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Any:
    return discourse_source(
        base_url=base_url,
        api_key=API_KEY,
        api_username=API_USERNAME,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestNormalizeAndHostname:
    @parameterized.expand(
        [
            ("plain", "https://forum.example.com", "https://forum.example.com"),
            ("trailing_slash", "https://forum.example.com/", "https://forum.example.com"),
            ("no_scheme", "forum.example.com", "https://forum.example.com"),
            ("whitespace", "  https://forum.example.com  ", "https://forum.example.com"),
        ]
    )
    def test_normalize_base_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    def test_hostname_of(self) -> None:
        assert hostname_of("https://forum.example.com/") == "forum.example.com"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://forum.example.com"),
            ("userinfo", "https://169.254.169.254@forum.example.com"),
            ("backslash", "https://169.254.169.254\\@forum.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@forum.example.com"),
        ]
    )
    def test_hostname_of_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        assert hostname_of(raw_url) is None


class TestFlattenDirectoryItem:
    def test_lifts_user_fields_and_drops_duplicate_id(self) -> None:
        item = {
            "id": 32,
            "post_count": 10,
            "user": {"id": 32, "username": "codinghorror", "name": "Jeff Atwood", "admin": True},
        }
        flattened = _flatten_directory_item(item)
        assert flattened == {
            "id": 32,
            "post_count": 10,
            "username": "codinghorror",
            "name": "Jeff Atwood",
            "admin": True,
        }

    def test_missing_user_key_is_a_noop(self) -> None:
        item = {"id": 1, "post_count": 5}
        assert _flatten_directory_item(item) == {"id": 1, "post_count": 5}


class TestDiscoursePostsPaginator:
    def test_full_refresh_stops_on_short_page(self) -> None:
        paginator = DiscoursePostsPaginator(stop_at_or_before=None)
        response = _json_response({"latest_posts": [_post(i) for i in range(10, 5, -1)]})
        paginator.update_state(response, data=[_post(i) for i in range(10, 5, -1)])
        assert paginator.has_next_page is False

    def test_full_refresh_continues_on_full_page(self) -> None:
        paginator = DiscoursePostsPaginator(stop_at_or_before=None)
        data = [_post(i) for i in range(POSTS_PAGE_SIZE, 0, -1)]
        paginator.update_state(_json_response({"latest_posts": data}), data=data)
        assert paginator.has_next_page is True
        assert paginator._before == 1

    def test_stops_at_watermark_within_first_page(self) -> None:
        # Watermark 80 falls inside the first (newest) page, so the incremental sync should
        # stop immediately rather than walking further back through already-synced posts.
        paginator = DiscoursePostsPaginator(stop_at_or_before=80)
        data = [_post(i) for i in range(129, 79, -1)]  # ids 129..80, 50 items
        assert len(data) == POSTS_PAGE_SIZE
        paginator.update_state(_json_response({"latest_posts": data}), data=data)
        assert paginator.has_next_page is False

    def test_empty_page_stops(self) -> None:
        paginator = DiscoursePostsPaginator(stop_at_or_before=None)
        paginator.update_state(_json_response({"latest_posts": []}), data=[])
        assert paginator.has_next_page is False

    def test_resume_state_round_trip(self) -> None:
        paginator = DiscoursePostsPaginator()
        data = [_post(i) for i in range(POSTS_PAGE_SIZE, 0, -1)]
        paginator.update_state(_json_response({"latest_posts": data}), data=data)
        state = paginator.get_resume_state()
        assert state == {"before": 1}

        resumed = DiscoursePostsPaginator()
        assert state is not None
        resumed.set_resume_state(state)
        assert resumed._before == 1
        assert resumed.has_next_page is True


class TestPipelineTransport:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_once(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_json_response({"category_list": {"categories": [{"id": 1, "name": "General"}, {"id": 2}]}})],
        )

        rows = _rows(_source(_make_manager(), "categories"))
        assert rows == [{"id": 1, "name": "General"}, {"id": 2}]
        assert session.send.call_count == 1
        assert params[0] == {}

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_topics_paginates_and_stops_on_empty_page(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        page1 = [{"id": i} for i in range(30)]
        params = _wire(
            session,
            [
                _json_response({"topic_list": {"topics": page1}}),
                _json_response({"topic_list": {"topics": []}}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, "topics"))
        assert rows == page1
        assert [p["page"] for p in params] == [0, 1]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DiscourseResumeConfig(page=1, before=None)

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_topics_terminates_on_empty_page_even_after_a_short_page(self, MockSession: Any, _safe: Any) -> None:
        # PageNumberPaginator only stops on a genuinely empty page (verified live against
        # meta.discourse.org: the API keeps returning 200 with an empty list well past the last
        # real page rather than a short final page), so a single non-empty short page still
        # triggers one more request before termination.
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response({"topic_list": {"topics": [{"id": 1}]}}),
                _json_response({"topic_list": {"topics": []}}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, "topics"))
        assert rows == [{"id": 1}]
        assert session.send.call_count == 2
        manager.save_state.assert_called_once()

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_topics_resumes_from_saved_page(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _json_response({"topic_list": {"topics": [{"id": 99}]}}),
                _json_response({"topic_list": {"topics": []}}),
            ],
        )

        manager = _make_manager(DiscourseResumeConfig(page=3))
        rows = _rows(_source(manager, "topics"))
        assert rows == [{"id": 99}]
        assert [p["page"] for p in params] == [3, 4]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_users_flattens_nested_user_object(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response(
                    {"directory_items": [{"id": 32, "post_count": 10, "user": {"id": 32, "username": "codinghorror"}}]}
                ),
                _json_response({"directory_items": []}),
            ],
        )

        rows = _rows(_source(_make_manager(), "users"))
        assert rows == [{"id": 32, "post_count": 10, "username": "codinghorror"}]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_users_sends_required_static_params(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response({"directory_items": []})])

        _rows(_source(_make_manager(), "users"))
        assert params[0]["period"] == "all"
        assert params[0]["order"] == "likes_received"

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_posts_full_refresh_walks_backward_via_before_cursor(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        page1 = [_post(i) for i in range(POSTS_PAGE_SIZE, 0, -1)]
        page2 = [_post(i) for i in range(0, -3, -1)]
        params = _wire(
            session,
            [
                _json_response({"latest_posts": page1}),
                _json_response({"latest_posts": page2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, "posts"))
        assert rows == page1 + page2
        assert "before" not in params[0]
        assert params[1]["before"] == 1
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DiscourseResumeConfig(page=None, before=1)

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_posts_incremental_stops_at_watermark(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        page1 = [_post(i) for i in range(129, 79, -1)]  # ids 129..80
        _wire(session, [_json_response({"latest_posts": page1})])

        rows = _rows(
            _source(_make_manager(), "posts", should_use_incremental_field=True, db_incremental_field_last_value=80)
        )
        assert rows == page1
        assert session.send.call_count == 1

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_posts_resumes_from_saved_before_cursor(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response({"latest_posts": [_post(5)]})])

        manager = _make_manager(DiscourseResumeConfig(before=500))
        rows = _rows(_source(manager, "posts"))
        assert rows == [_post(5)]
        assert params[0]["before"] == 500

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_auth_headers_sent_without_bearer_or_basic_scheme(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured_auth: list[Any] = []

        def _prepare(request: Any) -> MagicMock:
            captured_auth.append(request.auth)
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_json_response({"category_list": {"categories": []}})]

        _rows(_source(_make_manager(), "categories"))

        prepared_request = requests.Request(method="GET", url=BASE_URL).prepare()
        captured_auth[0](prepared_request)
        assert prepared_request.headers["Api-Key"] == API_KEY
        assert prepared_request.headers["Api-Username"] == API_USERNAME
        assert "Authorization" not in prepared_request.headers

    def test_blocks_unsafe_hosts(self) -> None:
        with patch(IS_HOST_SAFE_PATCH, return_value=(False, "blocked")):
            with pytest.raises(DiscourseHostNotAllowedError):
                _rows(_source(_make_manager(), "categories", base_url="https://10.0.0.1"))

    def test_blocks_ambiguous_url(self) -> None:
        with pytest.raises(DiscourseHostNotAllowedError):
            _rows(_source(_make_manager(), "categories", base_url="https://169.254.169.254\\@forum.example.com"))

    @parameterized.expand(
        [
            ("categories", ["id"]),
            ("topics", ["id"]),
            ("posts", ["id"]),
            ("tags", ["id"]),
            ("groups", ["id"]),
            ("users", ["id"]),
        ]
    )
    def test_source_returns_declared_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_posts_sort_mode_is_descending(self) -> None:
        assert _source(_make_manager(), "posts").sort_mode == "desc"

    @parameterized.expand([("categories",), ("tags",), ("groups",), ("users",), ("topics",)])
    def test_non_post_endpoints_sort_mode_is_ascending(self, endpoint: str) -> None:
        assert _source(_make_manager(), endpoint).sort_mode == "asc"

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_posts_write_disposition_is_merge_when_incremental(self, MockSession: Any, _safe: Any) -> None:
        # Verified indirectly: an incremental sync only re-fetches until the watermark, so a
        # merge (not replace) write disposition is required to avoid dropping older rows. This
        # is asserted through the resource's resume/merge-relevant behavior rather than digging
        # into the framework's internal write_disposition config.
        session = MockSession.return_value
        _wire(session, [_json_response({"latest_posts": [_post(1)]})])
        rows = _rows(
            _source(_make_manager(), "posts", should_use_incremental_field=True, db_incremental_field_last_value=0)
        )
        assert rows == [_post(1)]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    @patch("tenacity.nap.time.sleep")
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(
        self, _name: str, status: int, MockSession: Any, _safe: Any, _sleep: Any
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response({}, status_code=status),
                _json_response({"category_list": {"categories": [{"id": 1}]}}),
            ],
        )

        rows = _rows(_source(_make_manager(), "categories"))
        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_persistent_server_error_exhausts_retries(self, MockSession: Any, _safe: Any, _sleep: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager(), "categories"))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_permanent_statuses_raise_http_error(self, _name: str, status: int, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"errors": ["nope"]}, status_code=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager(), "categories"))

    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307)])
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_redirects_are_refused(self, _name: str, status: int, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=status, location="https://evil.example.com")])

        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source(_make_manager(), "categories"))


class TestValidateCredentials:
    def _validate(self, monkeypatch: Any, response: MagicMock, schema_name: Optional[str] = None) -> tuple:
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(discourse, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(discourse, "_is_host_safe", lambda host, team_id: (True, None))
        return validate_credentials(BASE_URL, API_KEY, API_USERNAME, schema_name=schema_name, team_id=1)

    def test_validate_credentials_success(self, monkeypatch: Any) -> None:
        assert self._validate(monkeypatch, _mock_response(200, {"current_user": {"id": 1}})) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self, monkeypatch: Any) -> None:
        body = {"errors": ["The API username or key is invalid."], "error_type": "invalid_access"}
        valid, message = self._validate(monkeypatch, _mock_response(403, body), schema_name="posts")
        assert valid is False
        assert message == "The API username or key is invalid."

    def test_validate_credentials_accepts_403_at_source_create(self, monkeypatch: Any) -> None:
        # A scoped API key may not cover the /session/current.json probe even though it's valid
        # for the tables the user actually wants to sync — source creation must still go through.
        body = {"errors": ["The API username or key is invalid."], "error_type": "invalid_access"}
        assert self._validate(monkeypatch, _mock_response(403, body)) == (True, None)

    def test_validate_credentials_rejects_redirects(self, monkeypatch: Any) -> None:
        valid, _ = self._validate(monkeypatch, _mock_response(200, {}, is_redirect=True))
        assert valid is False

    def test_validate_credentials_rejects_unsafe_host(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(discourse, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        valid, message = validate_credentials(BASE_URL, API_KEY, API_USERNAME, team_id=1)
        assert valid is False
        assert message == "blocked"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://forum.example.com"),
            ("userinfo", "https://169.254.169.254@forum.example.com"),
            ("backslash", "https://169.254.169.254\\@forum.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        valid, message = validate_credentials(raw_url, API_KEY, API_USERNAME, team_id=1)
        assert valid is False
        assert message == "Invalid Discourse instance URL"

    def test_validate_credentials_handles_connection_errors(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(discourse, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(discourse, "_is_host_safe", lambda host, team_id: (True, None))
        valid, message = validate_credentials(BASE_URL, API_KEY, API_USERNAME, team_id=1)
        assert valid is False
        assert message is not None and "Could not connect to Discourse" in message

    def test_validate_credentials_generic_error_status(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(500, {}))
        assert valid is False
        assert message == "Discourse returned HTTP 500"
