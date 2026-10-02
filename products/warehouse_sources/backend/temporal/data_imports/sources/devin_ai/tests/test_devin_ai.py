import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    DevinAIResumeConfig,
    _endpoint_path,
    devin_ai_source,
    get_status_code,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_status_code builds its own tracked session in the devin_ai module.
DEVIN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, has_next_page: bool = False, end_cursor: str | None = None
) -> Response:
    body: dict[str, Any] = {"has_next_page": has_next_page, "end_cursor": end_cursor}
    if items is not None:
        body["items"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _consumption_response(rows: list[dict[str, Any]], *, total_acus: float = 0.0) -> Response:
    # The consumption endpoints answer with one unpaginated object, not the cursor envelope.
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"total_acus": total_acus, "consumption_by_date": rows}).encode()
    return resp


def _make_manager(resume_state: DevinAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared rather than inspecting the final state after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_urls(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Like `_wire`, but capture each request's URL too so fan-out tests can tell a parent request
    from a per-parent child request."""
    session.headers = {}
    captured: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        captured.append((request.url or "", dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return captured


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return devin_ai_source(
        api_key="cog_test",
        org_id="org-abc",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestEndpointPath:
    @parameterized.expand(
        [
            ("sessions", "/v3/organizations/org-abc/sessions"),
            ("playbooks", "/v3/organizations/org-abc/playbooks"),
            ("knowledge_notes", "/v3/organizations/org-abc/knowledge/notes"),
            ("secrets", "/v3/organizations/org-abc/secrets"),
            ("session_insights", "/v3/organizations/org-abc/sessions/insights"),
            ("consumption_daily", "/v3/organizations/org-abc/consumption/daily"),
            # Members must stay on the org-scoped users listing: the v2 members endpoint only accepts
            # enterprise-admin personal API keys, which this source never stores.
            ("members", "/v3beta1/organizations/org-abc/members/users"),
        ]
    )
    def test_org_id_is_interpolated_into_path(self, endpoint: str, expected: str) -> None:
        assert _endpoint_path(endpoint, "org-abc") == expected

    @parameterized.expand(
        [
            ("path_traversal", "org-abc/../billing"),
            ("query_injection", "org-abc?first=1"),
            ("slash", "org/abc"),
            ("empty", ""),
            ("whitespace_only", "   "),
        ]
    )
    def test_malicious_org_id_is_rejected(self, _name: str, org_id: str) -> None:
        # A malformed org_id must not be able to inject `/` or `?` to route the stored key elsewhere.
        with pytest.raises(ValueError):
            _endpoint_path("sessions", org_id)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_items_as_dicts(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"session_id": "s1"}, {"session_id": "s2"}])])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_has_no_after_and_uses_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"session_id": "s1"}])])

        _rows(_source("sessions", _make_manager()))
        assert params[0] == {"first": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"session_id": "s1"}], has_next_page=True, end_cursor="cur1"),
                _response([{"session_id": "s2"}], has_next_page=False, end_cursor=None),
            ],
        )

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]
        # The second request must carry the cursor from the first page's end_cursor.
        assert params[1] == {"first": PAGE_SIZE, "after": "cur1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_next_page_false_even_if_cursor_present(self, MockSession) -> None:
        session = MockSession.return_value
        # A defensive guard: a cursor with has_next_page false must not loop.
        _wire(session, [_response([{"session_id": "s1"}], has_next_page=False, end_cursor="cur1")])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == [{"session_id": "s1"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"session_id": "s3"}])])

        _rows(_source("sessions", _make_manager(DevinAIResumeConfig(after="saved_cursor"))))
        assert params[0] == {"first": PAGE_SIZE, "after": "saved_cursor"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_cursor_at_page_boundary_only(self, MockSession) -> None:
        session = MockSession.return_value
        # State is saved once per completed page that has a successor, after the page is yielded — so a
        # crash re-fetches the last page (merge dedupes) rather than skipping its tail. No save after the
        # final page (nothing left to resume into).
        _wire(
            session,
            [
                _response([{"session_id": "s1"}], has_next_page=True, end_cursor="cur1"),
                _response([{"session_id": "s2"}], has_next_page=True, end_cursor="cur2"),
                _response([{"session_id": "s3"}], has_next_page=False, end_cursor=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("sessions", manager))
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert saved == [DevinAIResumeConfig(after="cur1"), DevinAIResumeConfig(after="cur2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_items_key_yields_no_rows_without_raising(self, MockSession) -> None:
        session = MockSession.return_value
        # The Devin envelope tolerates a page with no `items` key (defaults to empty) rather than failing.
        _wire(session, [_response(None, has_next_page=False, end_cursor=None)])

        rows = _rows(_source("sessions", _make_manager()))
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"session_id": "s1"}])])

        _rows(_source("sessions", _make_manager()))
        # The token is applied via the framework auth (redacted), not a hand-built header on the session.
        assert session.headers.get("Authorization") is None
        assert session.auth is not None


class TestGetStatusCode:
    def test_returns_status_and_probes_with_first_one(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch(DEVIN_SESSION_PATCH, return_value=session):
            status = get_status_code("cog_test", "org-abc", "sessions")

        assert status == 200
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"first": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer cog_test"

    @parameterized.expand(
        [
            # A fan-out child's own path needs a parent id, so probing it directly would send a URL
            # with an unbound `{devin_id}` / `{user_id}` placeholder. Each delegates to the org-level
            # endpoint gated by the same permission instead.
            ("session_messages", "https://api.devin.ai/v3/organizations/org-abc/sessions", {"first": 1}),
            (
                "consumption_daily_users",
                "https://api.devin.ai/v3/organizations/org-abc/consumption/daily",
                {},
            ),
        ]
    )
    def test_fanout_child_probes_its_org_level_endpoint(
        self, endpoint: str, expected_url: str, expected_params: dict[str, Any]
    ) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch(DEVIN_SESSION_PATCH, return_value=session):
            get_status_code("cog_test", "org-abc", endpoint)

        args, kwargs = session.get.call_args
        assert args[0] == expected_url
        assert kwargs["params"] == expected_params


class TestDevinAISource:
    @parameterized.expand(["sessions", "session_insights", "playbooks", "knowledge_notes", "secrets"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        cfg = DEVIN_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # created_at is a stable field — never updated_at — so partitions don't rewrite each sync.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    @parameterized.expand(
        [
            ("session_messages", ["session_id", "event_id"]),
            ("consumption_daily", ["date"]),
            ("consumption_daily_users", ["user_id", "date"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_and_consumption_tables_keep_their_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], MockSession
    ) -> None:
        # The fan-out and single-page branches build their SourceResponse separately from the
        # top-level one, so each has to carry the composite key that keeps rows from colliding
        # across parents, and a partition key that doesn't move once written.
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == (["date"] if endpoint.startswith("consumption") else ["created_at"])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_source_response_dedupes_on_user_id_and_has_no_partition(self, MockSession) -> None:
        response = _source("members", _make_manager())
        assert response.name == "members"
        assert response.primary_keys == ["user_id"]
        # Member records carry no created_at, so the table must not declare a datetime partition.
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestMembersJoin:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_member_user_id_and_email_pass_through_for_sessions_join(self, MockSession) -> None:
        session = MockSession.return_value
        # Devin identifies people by Auth0-style subjects (`email|<id>`, `google-oauth2|<id>`), and the
        # sessions table's user_id lands as that same opaque string. The members table must surface
        # user_id byte-identical to the API value so sessions.user_id = members.user_id resolves an email.
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "user_id": "email|1a2b3c4d5e6f",
                            "email": "casey@example.com",
                            "name": "Casey Doe",
                            "role_assignments": [
                                {
                                    "org_id": "org-abc",
                                    "role": {"role_id": "r1", "role_name": "Member", "role_type": "org"},
                                }
                            ],
                        },
                        {
                            "user_id": "google-oauth2|110000000000000000001",
                            "email": "riley@example.com",
                            "name": "Riley Roe",
                            "role_assignments": [],
                        },
                    ]
                )
            ],
        )

        rows = _rows(_source("members", _make_manager()))

        email_by_user_id = {row["user_id"]: row["email"] for row in rows}
        # user_id exactly as it lands in the synced sessions table.
        assert email_by_user_id["email|1a2b3c4d5e6f"] == "casey@example.com"
        assert email_by_user_id["google-oauth2|110000000000000000001"] == "riley@example.com"
        assert rows[0]["name"] == "Casey Doe"
        assert rows[0]["role_assignments"][0]["role"]["role_name"] == "Member"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_pagination_follows_cursor_so_later_pages_join(self, MockSession) -> None:
        session = MockSession.return_value
        # A member past the first page must still be synced, or their sessions stop resolving to an email.
        params = _wire(
            session,
            [
                _response(
                    [{"user_id": "email|aaa111", "email": "casey@example.com", "name": None, "role_assignments": []}],
                    has_next_page=True,
                    end_cursor="cur1",
                ),
                _response(
                    [{"user_id": "email|bbb222", "email": "riley@example.com", "name": None, "role_assignments": []}],
                    has_next_page=False,
                    end_cursor=None,
                ),
            ],
        )

        rows = _rows(_source("members", _make_manager()))

        assert params[1] == {"first": PAGE_SIZE, "after": "cur1"}
        email_by_user_id = {row["user_id"]: row["email"] for row in rows}
        assert email_by_user_id["email|bbb222"] == "riley@example.com"


class TestConsumption:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_daily_selects_rows_from_the_consumption_envelope_in_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        # The consumption body nests its rows under `consumption_by_date`, and carries no cursor —
        # selecting `items` or paginating it would sync nothing and loop respectively.
        params = _wire(
            session,
            [
                _consumption_response(
                    [
                        {"date": 1750000000, "acus": 12.5, "acus_by_product": {"devin": 12.5}},
                        {"date": 1750086400, "acus": 3.0, "acus_by_product": {"devin": 3.0}},
                    ],
                    total_acus=15.5,
                )
            ],
        )

        rows = _rows(_source("consumption_daily", _make_manager()))

        assert [row["date"] for row in rows] == [1750000000, 1750086400]
        assert rows[0]["acus"] == 12.5
        assert session.send.call_count == 1
        # The endpoint takes no page-size param; sending one would be undocumented.
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_daily_users_fans_out_over_members_and_stamps_the_member_on_each_row(self, MockSession) -> None:
        session = MockSession.return_value
        # Per-user consumption rows are just date + ACUs, so without the parent's user_id copied down
        # the table would be unattributable — and every member's rows would collide on `date`.
        reqs = _wire_urls(
            session,
            [
                _response([{"user_id": "email|aaa111"}, {"user_id": "email|bbb222"}]),
                _consumption_response([{"date": 1750000000, "acus": 4.0, "acus_by_product": {"devin": 4.0}}]),
                _consumption_response([{"date": 1750000000, "acus": 7.0, "acus_by_product": {"devin": 7.0}}]),
            ],
        )

        rows = _rows(_source("consumption_daily_users", _make_manager()))

        assert {(row["user_id"], row["acus"]) for row in rows} == {("email|aaa111", 4.0), ("email|bbb222", 7.0)}
        child_urls = [url for url, _params in reqs if "/consumption/daily/users/" in url]
        assert {url.rsplit("/", 1)[1] for url in child_urls} == {"email|aaa111", "email|bbb222"}
        parent = next(params for url, params in reqs if url.endswith("/members/users"))
        assert parent["first"] == PAGE_SIZE


class TestSessionMessagesFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_messages_are_fetched_per_session_and_carry_their_session_id(self, MockSession) -> None:
        session = MockSession.return_value
        # Message rows carry no session id of their own, so the parent's has to be copied down —
        # otherwise the (session_id, event_id) primary key can't be formed.
        reqs = _wire_urls(
            session,
            [
                _response([{"session_id": "devin-1"}, {"session_id": "devin-2"}]),
                _response([{"event_id": "e1", "source": "user", "message": "hi", "created_at": 1750000000}]),
                _response([{"event_id": "e1", "source": "devin", "message": "on it", "created_at": 1750000100}]),
            ],
        )

        rows = _rows(_source("session_messages", _make_manager()))

        assert {(row["session_id"], row["event_id"]) for row in rows} == {("devin-1", "e1"), ("devin-2", "e1")}
        # The un-renamed parent-prefixed key must not survive into the table.
        assert all("_sessions_session_id" not in row for row in rows)
        child = [(url, params) for url, params in reqs if url.endswith("/messages")]
        assert {url.split("/sessions/")[1].split("/")[0] for url, _params in child} == {"devin-1", "devin-2"}
        # The messages endpoint cursor-paginates like the rest of v3, so it takes a page size.
        assert all(params["first"] == PAGE_SIZE for _url, params in child)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_session_with_more_messages_than_one_page_is_fully_walked(self, MockSession) -> None:
        session = MockSession.return_value
        reqs = _wire_urls(
            session,
            [
                _response([{"session_id": "devin-1"}]),
                _response([{"event_id": "e1"}], has_next_page=True, end_cursor="cur1"),
                _response([{"event_id": "e2"}], has_next_page=False, end_cursor=None),
            ],
        )

        rows = _rows(_source("session_messages", _make_manager()))

        assert [row["event_id"] for row in rows] == ["e1", "e2"]
        child = [params for url, params in reqs if url.endswith("/messages")]
        assert child[1]["after"] == "cur1"
