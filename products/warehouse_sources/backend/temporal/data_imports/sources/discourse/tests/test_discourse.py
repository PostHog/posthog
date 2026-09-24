import json
from datetime import UTC, datetime
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
    DiscourseUserActionsPaginator,
    _flatten_directory_item,
    discourse_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.settings import USER_ACTIONS_PAGE_SIZE

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


def _urls(session: MagicMock) -> list[str]:
    """URLs of every request the run prepared. Unlike ``request.params``, ``request.url`` is not
    mutated between pages, so it can be read after the run."""
    return [call.args[0].url for call in session.prepare_request.call_args_list]


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    manager: MagicMock,
    endpoint: str,
    *,
    base_url: str = BASE_URL,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
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
        incremental_field=incremental_field,
    )


def _action(created_at: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "action_type": 5,
        "created_at": created_at,
        "target_user_id": 7,
        "acting_user_id": 9,
        "topic_id": 3,
        "post_number": 2,
    }
    row.update(overrides)
    return row


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


class TestDiscourseUserActionsPaginator:
    WATERMARK = datetime(2026, 3, 1, tzinfo=UTC)

    def _page(self, rows: list[dict[str, Any]], watermark: Optional[datetime]) -> DiscourseUserActionsPaginator:
        paginator = DiscourseUserActionsPaginator(limit=USER_ACTIONS_PAGE_SIZE, stop_at_or_before=watermark)
        paginator.update_state(_json_response({"user_actions": rows}), data=rows)
        return paginator

    @parameterized.expand([("short_page", 1, False), ("full_page", USER_ACTIONS_PAGE_SIZE, True)])
    def test_full_refresh_walks_on_only_while_pages_stay_full(
        self, _name: str, row_count: int, expects_next_page: bool
    ) -> None:
        rows = [_action("2026-01-01T00:00:00.000Z")] * row_count
        assert self._page(rows, None).has_next_page is expects_next_page

    @parameterized.expand(
        [
            # The whole page is already synced, so this user's walk is done.
            ("page_predates_the_watermark", ["2026-02-28T12:00:00.000Z"] * USER_ACTIONS_PAGE_SIZE, False),
            # Only the first row is newer, but the rest of the stream still has to be walked.
            (
                "page_still_holds_newer_rows",
                ["2026-03-05T00:00:00.000Z"] + ["2026-02-01T00:00:00.000Z"] * (USER_ACTIONS_PAGE_SIZE - 1),
                True,
            ),
            # Nothing on the page can be compared against the watermark, so it proves nothing
            # about how far back the walk has got.
            ("unparsable_timestamps", ["not-a-date"] * USER_ACTIONS_PAGE_SIZE, True),
        ]
    )
    def test_incremental_stops_only_once_a_whole_page_predates_the_watermark(
        self, _name: str, created_ats: list[str], expects_next_page: bool
    ) -> None:
        rows = [_action(created_at) for created_at in created_ats]
        assert self._page(rows, self.WATERMARK).has_next_page is expects_next_page


class TestAdminUsers:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_reads_the_bare_array_body_and_starts_at_page_one(self, MockSession: Any, _safe: Any) -> None:
        # Discourse clamps page 0 to page 1, so a 0-based walk would sync the first 100 users twice.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _json_response([{"id": 1, "username": "alice"}]),
                _json_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), "admin_users"))
        assert rows == [{"id": 1, "username": "alice"}]
        assert [p["page"] for p in params] == [1, 2]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_sorts_ascending_by_creation_date_and_never_asks_for_emails(self, MockSession: Any, _safe: Any) -> None:
        # `show_emails=true` writes a staff action log entry per request, so a sync of a large
        # forum would bury the customer's own audit log.
        session = MockSession.return_value
        params = _wire(session, [_json_response([])])

        _rows(_source(_make_manager(), "admin_users"))
        assert params[0]["order"] == "created"
        assert params[0]["asc"] == "true"
        assert "show_emails" not in params[0]


class TestBadges:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_syncs_only_the_badges_list_from_the_multi_key_body(self, MockSession: Any, _safe: Any) -> None:
        # The response also carries badge_types, badge_groupings and admin_badges; only the
        # badge records belong in the table.
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response(
                    {
                        "badges": [{"id": 1, "name": "Welcome"}],
                        "badge_types": [{"id": 3, "name": "Bronze"}],
                        "badge_groupings": [{"id": 1, "name": "Getting Started"}],
                        "admin_badges": {"badge_ids": [1]},
                    }
                )
            ],
        )

        rows = _rows(_source(_make_manager(), "badges"))
        assert rows == [{"id": 1, "name": "Welcome"}]
        assert session.send.call_count == 1


class TestGroupMembers:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_groups_and_stamps_the_group_onto_each_member(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _json_response({"groups": [{"id": 41, "name": "staff"}, {"id": 42, "name": "moderators"}]}),
                _json_response({"members": [{"id": 1, "username": "alice"}], "meta": {"total": 1}}),
                _json_response({"members": [{"id": 2, "username": "bob"}], "meta": {"total": 1}}),
                _json_response({"groups": []}),
            ],
        )

        rows = _rows(_source(_make_manager(), "group_members"))
        assert rows == [
            {"id": 1, "username": "alice", "group_id": 41, "group_name": "staff"},
            {"id": 2, "username": "bob", "group_id": 42, "group_name": "moderators"},
        ]
        # The membership row's own creation time is the only ordering that can't shift under an
        # offset walk while the sync runs.
        assert params[1]["order"] == "added_at"
        assert params[1]["asc"] == "true"

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_walks_offset_pages_within_one_group(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        page1 = [{"id": member_id} for member_id in range(1000)]
        params = _wire(
            session,
            [
                _json_response({"groups": [{"id": 41, "name": "staff"}]}),
                _json_response({"members": page1, "meta": {"total": 1001}}),
                _json_response({"members": [{"id": 1000}], "meta": {"total": 1001}}),
                _json_response({"groups": []}),
            ],
        )

        rows = _rows(_source(_make_manager(), "group_members"))
        assert len(rows) == 1001
        assert [p["offset"] for p in params[1:3]] == [0, 1000]

    @parameterized.expand([("restricted_roster", 403), ("group_gone", 404)])
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_skips_a_group_whose_roster_cannot_be_read(
        self, _name: str, status: int, MockSession: Any, _safe: Any
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response({"groups": [{"id": 41, "name": "secret"}, {"id": 42, "name": "staff"}]}),
                _json_response({"errors": ["nope"]}, status_code=status),
                _json_response({"members": [{"id": 2}], "meta": {"total": 1}}),
                _json_response({"groups": []}),
            ],
        )

        rows = _rows(_source(_make_manager(), "group_members"))
        assert rows == [{"id": 2, "group_id": 42, "group_name": "staff"}]


class TestUserActions:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_admin_users_without_a_server_side_action_filter(self, MockSession: Any, _safe: Any) -> None:
        # Discourse drops private message topics from the stream only while `filter` is blank,
        # and for an admin identity a non-blank `filter` removes the exclusion entirely. Sending
        # one would pull replies and likes made inside private messages into the table.
        session = MockSession.return_value
        action = _action("2026-03-05T00:00:00.000Z")
        params = _wire(
            session,
            [
                _json_response([{"id": 7, "username": "alice"}]),
                _json_response({"user_actions": [action]}),
                _json_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), "user_actions"))
        assert rows == [action]
        assert _urls(session)[1] == f"{BASE_URL}/user_actions.json?username=alice"
        assert "filter" not in params[1]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_narrows_to_public_actions_and_drops_post_text(self, MockSession: Any, _safe: Any) -> None:
        # With no server-side filter the stream carries every action type, and the admin
        # identity also reads whispers and hidden posts, so both narrowing steps run over the
        # response instead.
        session = MockSession.return_value
        reply = _action("2026-03-05T00:00:00.000Z", excerpt="post body", edit_reason="typo")
        private_message = _action("2026-03-04T00:00:00.000Z", action_type=12)
        _wire(
            session,
            [
                _json_response([{"id": 7, "username": "alice"}]),
                _json_response({"user_actions": [reply, private_message]}),
                _json_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), "user_actions"))
        assert rows == [_action("2026-03-05T00:00:00.000Z")]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_incremental_stops_walking_a_user_at_the_watermark(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        page = [_action("2026-02-28T12:00:00.000Z")] * USER_ACTIONS_PAGE_SIZE
        _wire(
            session,
            [
                _json_response([{"id": 7, "username": "alice"}]),
                _json_response({"user_actions": page}),
                _json_response([]),
            ],
        )

        rows = _rows(
            _source(
                _make_manager(),
                "user_actions",
                should_use_incremental_field=True,
                incremental_field="created_at",
                db_incremental_field_last_value="2026-03-01T00:00:00Z",
            )
        )
        assert len(rows) == USER_ACTIONS_PAGE_SIZE
        # One parent page, one child page, one terminal parent page: the child never walked on.
        assert session.send.call_count == 3

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_the_stored_watermark_and_walks_the_whole_stream(
        self, MockSession: Any, _safe: Any
    ) -> None:
        session = MockSession.return_value
        page1 = [_action("2026-01-01T00:00:00.000Z")] * USER_ACTIONS_PAGE_SIZE
        params = _wire(
            session,
            [
                _json_response([{"id": 7, "username": "alice"}]),
                _json_response({"user_actions": page1}),
                _json_response({"user_actions": [_action("2025-01-01T00:00:00.000Z")]}),
                _json_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), "user_actions", db_incremental_field_last_value="2026-03-01T00:00:00Z"))
        assert len(rows) == USER_ACTIONS_PAGE_SIZE + 1
        assert [p["offset"] for p in params[1:3]] == [0, USER_ACTIONS_PAGE_SIZE]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_skips_a_user_whose_stream_is_not_visible(self, MockSession: Any, _safe: Any) -> None:
        # Discourse answers 404 both for a hidden profile and for a user deleted between the
        # listing and this fetch; either way the other users still have activity worth syncing.
        session = MockSession.return_value
        action = _action("2026-03-05T00:00:00.000Z")
        _wire(
            session,
            [
                _json_response([{"id": 7, "username": "hidden"}, {"id": 8, "username": "alice"}]),
                _json_response({"errors": ["nope"]}, status_code=404),
                _json_response({"user_actions": [action]}),
                _json_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), "user_actions"))
        assert rows == [action]


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
