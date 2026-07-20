import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import (
    AUTH_ERROR_MESSAGE,
    BigMailerAuthError,
    BigMailerResumeConfig,
    bigmailer_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the bigmailer module.
BIGMAILER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer.make_tracked_session"
)


def _response(body: dict[str, Any] | None = None, *, status: int = 200, text: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = text.encode() if text is not None else json.dumps(body if body is not None else {}).encode()
    return resp


def _page(items: list[dict[str, Any]], *, has_more: bool = False, cursor: str | None = None) -> Response:
    # The API always returns a `cursor`; only `has_more` tells us another page exists.
    return _response({"data": items, "has_more": has_more, "cursor": cursor if cursor is not None else "ignored"})


def _make_manager(resume_state: BigMailerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session and return (url, params) snapshots captured AT SEND TIME.

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


def _source(endpoint: str, manager: mock.MagicMock | None = None) -> SourceResponse:
    return bigmailer_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "b1", "created": 1}], has_more=True, cursor="C2=="),
                _page([{"id": "b2", "created": 2}], has_more=False, cursor="ignored"),
            ],
        )

        rows = _rows(_source("brands"))

        assert [r["id"] for r in rows] == ["b1", "b2"]
        assert snapshots[0][1] == {"limit": 100}
        # second request must carry the cursor from page one
        assert snapshots[1][1] == {"limit": 100, "cursor": "C2=="}
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_inject_brand_id_for_top_level(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "b1", "created": 1}])])

        rows = _rows(_source("brands"))
        assert "brand_id" not in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_cursor_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "b1"}], has_more=True, cursor="C2=="), _page([{"id": "b2"}])])

        manager = _make_manager()
        _rows(_source("brands", manager))

        # one save (for the single page boundary that had a next page); none after the terminal page
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BigMailerResumeConfig(cursor="C2==")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([{"id": "b2"}])])

        manager = _make_manager(BigMailerResumeConfig(cursor="RESUME==", brand_id=None))
        _rows(_source("brands", manager))

        assert snapshots[0][1]["cursor"] == "RESUME=="


class TestBrandFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_every_brand_and_injects_brand_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "b1"}, {"id": "b2"}]),  # /brands
                _page([{"id": "c1", "created": 1}]),  # b1 contacts
                _page([{"id": "c2", "created": 2}]),  # b2 contacts
            ],
        )

        rows = _rows(_source("contacts"))

        assert [(r["id"], r["brand_id"]) for r in rows] == [("c1", "b1"), ("c2", "b2")]
        # the injected brand id must be the plain `brand_id` column, not the prefixed parent key
        assert rows[0] == {"id": "c1", "created": 1, "brand_id": "b1"}
        assert snapshots[1][0].endswith("/brands/b1/contacts")
        assert snapshots[2][0].endswith("/brands/b2/contacts")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_within_a_brand(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "b1"}]),  # /brands
                _page([{"id": "c1"}], has_more=True, cursor="P2=="),  # b1 contacts page 1
                _page([{"id": "c2"}]),  # b1 contacts page 2
            ],
        )

        rows = _rows(_source("contacts"))

        assert [r["id"] for r in rows] == ["c1", "c2"]
        assert snapshots[2][0].endswith("/brands/b1/contacts")
        assert snapshots[2][1]["cursor"] == "P2=="

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_the_brand_list_itself(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "b1"}], has_more=True, cursor="B2=="),  # /brands page 1
                _page([{"id": "c1"}]),  # b1 contacts
                _page([{"id": "b2"}]),  # /brands page 2
                _page([{"id": "c2"}]),  # b2 contacts
            ],
        )

        rows = _rows(_source("contacts"))
        assert [(r["id"], r["brand_id"]) for r in rows] == [("c1", "b1"), ("c2", "b2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_brands_and_resumes_cursor(self, MockSession) -> None:
        # Resuming mid-fan-out must not re-request brands completed before the crash, and must start
        # the in-progress brand from its saved cursor.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "b1"}, {"id": "b2"}, {"id": "b3"}]),  # /brands
                _page([{"id": "c2"}]),  # b2 contacts (resumed)
                _page([{"id": "c3"}]),  # b3 contacts (fresh)
            ],
        )

        manager = _make_manager(
            BigMailerResumeConfig(
                fanout_state={
                    "completed": ["/brands/b1/contacts"],
                    "current": "/brands/b2/contacts",
                    "child_state": {"cursor": "MID=="},
                }
            )
        )
        rows = _rows(_source("contacts", manager))

        urls = [url for url, _params in snapshots]
        assert not any("/brands/b1/contacts" in url for url in urls)
        assert snapshots[1][0].endswith("/brands/b2/contacts")
        assert snapshots[1][1]["cursor"] == "MID=="
        assert snapshots[2][0].endswith("/brands/b3/contacts")
        assert "cursor" not in snapshots[2][1]
        assert [r["id"] for r in rows] == ["c2", "c3"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_resume_state_starts_fresh(self, MockSession) -> None:
        # An old-shape bookmark (cursor + brand_id, no fanout_state) can't be translated into the
        # framework's completed/current map — the fan-out restarts from the first brand instead.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"id": "b1"}, {"id": "b2"}]),  # /brands
                _page([{"id": "c1"}]),  # b1 contacts
                _page([{"id": "c2"}]),  # b2 contacts
            ],
        )

        manager = _make_manager(BigMailerResumeConfig(cursor="MID==", brand_id="b2"))
        rows = _rows(_source("contacts", manager))

        assert [(r["id"], r["brand_id"]) for r in rows] == [("c1", "b1"), ("c2", "b2")]
        assert all("cursor" not in params for _url, params in snapshots)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_brands(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "b1"}, {"id": "b2"}]),
                _page([{"id": "c1"}]),
                _page([{"id": "c2"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("contacts", manager))

        # after finishing b1 a checkpoint marks it completed, so a crash resumes on b2, not b1
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(
            state.fanout_state is not None and "/brands/b1/contacts" in state.fanout_state["completed"]
            for state in saved
        )


class TestResumeConfigCompatibility:
    def test_old_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved by the
        # pre-framework implementation must keep loading after the migration.
        state = BigMailerResumeConfig(**{"cursor": "C2==", "brand_id": "b1"})
        assert state.cursor == "C2=="
        assert state.brand_id == "b1"
        assert state.fanout_state is None


class TestAuthErrors:
    @parameterized.expand(
        [
            ("invalid_key_400", 400, '{"message":"Invalid api key"}'),
            ("unauthorized_401", 401, ""),
            ("forbidden_403", 403, ""),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failures_raise_non_retryable(self, _name: str, status: int, text: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status=status, text=text)])

        with pytest.raises(BigMailerAuthError) as exc:
            _rows(_source("brands"))
        assert str(exc.value) == AUTH_ERROR_MESSAGE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failure_on_a_brand_child_list_raises_non_retryable(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "b1"}]), _response(status=401, text="")])

        with pytest.raises(BigMailerAuthError):
            _rows(_source("contacts"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_auth_400_raises_http_error_not_auth_error(self, MockSession) -> None:
        # A 400 that isn't about the api key (e.g. a malformed param) must not be misreported as a
        # credential problem — otherwise a transient request bug would permanently disable the source.
        session = MockSession.return_value
        _wire(session, [_response(status=400, text='{"message":"bad cursor"}')])

        with pytest.raises(requests.HTTPError):
            _rows(_source("brands"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_404_raises_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status=404, text="not found")])

        with pytest.raises(requests.HTTPError):
            _rows(_source("brands"))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("invalid", 400, False), ("forbidden", 403, False)])
    @mock.patch(BIGMAILER_SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(BIGMAILER_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("brands", ["id"]),
            ("users", ["id"]),
            ("contacts", ["brand_id", "id"]),
            ("bulk_campaigns", ["brand_id", "id"]),
            ("suppression_lists", ["brand_id", "id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_partitions_on_created_by_month(self) -> None:
        response = _source("contacts")
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created"]
