import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer import (
    BeamerResumeConfig,
    _format_datetime,
    beamer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.settings import BEAMER_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the beamer module.
BEAMER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.getbeamer.com/v0/mock"
    resp.reason = "Error" if status >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BeamerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session, returning (url, params) snapshots captured AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return beamer_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestValidateCredentials:
    @parameterized.expand(
        [
            # 200 = good key, 403 = real key missing the optional 'Read posts' permission — both valid.
            ("ok", 200, True, None),
            ("forbidden_is_valid_key", 403, True, None),
            ("unauthorized_is_invalid", 401, False, "Invalid Beamer API key"),
            # A 5xx is inconclusive — never reported as an invalid key (would prompt a needless rotation).
            ("server_error_is_inconclusive", 500, False, "could not validate"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(BEAMER_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("key")
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message

    def test_network_error_is_inconclusive_not_invalid(self) -> None:
        # A transport failure must not be reported as an invalid key.
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError()
        with mock.patch(BEAMER_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not reach Beamer" in message

    def test_probe_sends_api_key_header(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(BEAMER_SESSION_PATCH, return_value=session):
            validate_credentials("key")
        _, kwargs = session.get.call_args
        assert kwargs["headers"]["Beamer-Api-Key"] == "key"


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i, "date": "2026-01-01"} for i in range(10)]
        snapshots = _wire(session, [_response(full_page), _response([{"id": 10, "date": "2026-01-02"}])])

        rows = _rows(_source("posts"))

        assert [r["id"] for r in rows] == list(range(11))
        # Stops after the short second page; never requests page 3.
        assert session.send.call_count == 2
        assert snapshots[0][0] == "https://api.getbeamer.com/v0/posts"
        assert snapshots[0][1] == {"maxResults": 10, "page": 1}
        assert snapshots[1][1] == {"maxResults": 10, "page": 2}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source("posts")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_adds_datefrom(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1, "date": "2026-03-05"}])])

        rows = _rows(
            _source(
                "posts",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="date",
            )
        )

        assert rows == [{"id": 1, "date": "2026-03-05"}]
        assert snapshots[0][1]["dateFrom"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_datefrom_without_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1, "date": "2026-01-01"}])])

        _rows(_source("posts"))
        assert "dateFrom" not in snapshots[0][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_nps_uses_larger_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1, "date": "2026-01-01", "score": 9}])])

        rows = _rows(_source("nps"))
        assert rows[0]["score"] == 9
        assert snapshots[0][0] == "https://api.getbeamer.com/v0/nps"
        assert snapshots[0][1]["maxResults"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 99, "date": "2026-01-01"}])])

        manager = _make_manager(BeamerResumeConfig(page=3, parent_id=None))
        rows = _rows(_source("posts", manager=manager))

        assert rows == [{"id": 99, "date": "2026-01-01"}]
        assert snapshots[0][1]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_checkpoints_next_page_and_short_page_does_not(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i, "date": "2026-01-01"} for i in range(10)]
        _wire(session, [_response(full_page), _response([{"id": 10, "date": "2026-01-02"}])])

        manager = _make_manager()
        _rows(_source("posts", manager=manager))

        # The checkpoint fires AFTER a page is yielded and points at the next page, so a crash
        # re-fetches the last checkpointed page (merge dedupes) rather than skipping rows. The
        # short final page leaves no checkpoint behind.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BeamerResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unexpected"})])

        # A 200 body that isn't a bare array means the response shape changed — fail loud, not 0 rows.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("posts"))


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_parent_id_into_child_rows(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "C1", "date": "2026-01-01", "text": "hi"}]),
                _response([{"id": "C2", "date": "2026-01-02", "text": "yo"}]),
            ],
        )

        rows = _rows(_source("post_comments"))

        assert rows == [
            {"id": "C1", "date": "2026-01-01", "text": "hi", "post_id": "P1"},
            {"id": "C2", "date": "2026-01-02", "text": "yo", "post_id": "P2"},
        ]
        assert [url for url, _ in snapshots] == [
            "https://api.getbeamer.com/v0/posts",
            "https://api.getbeamer.com/v0/posts/P1/comments",
            "https://api.getbeamer.com/v0/posts/P2/comments",
        ]
        # Child pages use the child's page size, not the parent's.
        assert snapshots[1][1] == {"maxResults": 10, "page": 1}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_numeric_parent_id_is_stringified(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 42}]),
                _response([{"id": "C1", "date": "2026-01-01"}]),
            ],
        )

        rows = _rows(_source("post_comments"))
        # The composite primary key column keeps the string shape the hand-rolled source produced.
        assert rows == [{"id": "C1", "date": "2026-01-01", "post_id": "42"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_feature_request_votes_inject_feature_request_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "R1"}]),
                _response([{"id": "V1", "date": "2026-01-01"}]),
            ],
        )

        rows = _rows(_source("feature_request_votes"))
        assert rows == [{"id": "V1", "date": "2026-01-01", "feature_request_id": "R1"}]
        assert snapshots[1][0] == "https://api.getbeamer.com/v0/requests/R1/votes"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_parent_404_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response({"error": "not found"}, status=404),
                _response([{"id": "C2", "date": "2026-01-02"}]),
            ],
        )

        # A parent deleted between enumeration and the child fetch 404s — skip it rather than
        # failing the whole sync; the remaining parents still sync.
        rows = _rows(_source("post_comments"))
        assert rows == [{"id": "C2", "date": "2026-01-02", "post_id": "P2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_404_error_propagates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "P1"}]),
                _response({"error": "forbidden"}, status=403),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_source("post_comments"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_parents_and_resumes_child_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "C9", "date": "2026-01-09"}]),
            ],
        )

        manager = _make_manager(
            BeamerResumeConfig(
                fanout_state={
                    "completed": ["/posts/P1/comments"],
                    "current": "/posts/P2/comments",
                    "child_state": {"page": 2},
                }
            )
        )
        rows = _rows(_source("post_comments", manager=manager))

        assert rows == [{"id": "C9", "date": "2026-01-09", "post_id": "P2"}]
        assert [url for url, _ in snapshots] == [
            "https://api.getbeamer.com/v0/posts",
            "https://api.getbeamer.com/v0/posts/P2/comments",
        ]
        assert snapshots[1][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_fanout_state_as_parents_complete(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "C1", "date": "2026-01-01"}]),
                _response([{"id": "C2", "date": "2026-01-02"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("post_comments", manager=manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert all(isinstance(state, BeamerResumeConfig) and state.fanout_state is not None for state in saved)
        # The final checkpoint records both parents as fully synced with no child mid-stream.
        final = saved[-1].fanout_state
        assert final == {
            "completed": ["/posts/P1/comments", "/posts/P2/comments"],
            "current": None,
            "child_state": None,
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_state_restarts_fanout(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "C1", "date": "2026-01-01"}]),
                _response([{"id": "C2", "date": "2026-01-02"}]),
            ],
        )

        # A pre-migration bookmark (parent_id) can't seed the framework fan-out — the sync starts
        # that part fresh and merge dedupes the re-pulled rows.
        manager = _make_manager(BeamerResumeConfig(page=2, parent_id="P2"))
        rows = _rows(_source("post_comments", manager=manager))

        assert [r["post_id"] for r in rows] == ["P1", "P2"]
        assert snapshots[1][1]["page"] == 1

    def test_old_shape_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved before the
        # migration must still construct.
        state = BeamerResumeConfig(**{"page": 3, "parent_id": "P2"})
        assert state.page == 3
        assert state.parent_id == "P2"
        assert state.fanout_state is None


class TestBeamerSourceResponse:
    @parameterized.expand(
        [
            ("posts", ["id"], "date", "desc"),
            ("feature_requests", ["id"], "date", "desc"),
            ("nps", ["id"], "date", "desc"),
            ("users", ["beamerId"], "firstSeen", "asc"),
            ("post_comments", ["post_id", "id"], "date", "asc"),
            ("feature_request_votes", ["feature_request_id", "id"], "date", "asc"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str, MockSession
    ) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == sort_mode

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoints_sort_desc(self, MockSession) -> None:
        # Endpoints with a server-side dateFrom filter must use "desc" so the watermark is only
        # persisted at the end of a successful sync (we can't verify the API's default sort order).
        for name, config in BEAMER_ENDPOINTS.items():
            response = _source(name)
            expected = "desc" if config.supports_incremental else "asc"
            assert response.sort_mode == expected, name
