import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
import time_machine
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend import mailersend
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.mailersend import (
    MailerSendResumeConfig,
    _activity_date_window,
    _to_datetime,
    check_credentials,
    mailersend_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import MAILERSEND_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"

BASE = "https://api.mailersend.com/v1"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = BASE
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    return _response({"data": items, "links": {"next": next_url}})


def _make_manager(resume_state: MailerSendResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting it after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        params = dict(request.params or {})
        snapshots.append({"url": request.url, **params})
        prepared = MagicMock()
        prepared.url = request.url + (("?" + urlencode(params)) if params else "")
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: MagicMock, **kw: Any) -> Any:
    return mailersend_source(
        api_token="mlsn.token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kw,
    )


class TestToDatetime:
    @parameterized.expand(
        [
            (
                "aware_datetime",
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("date_value", date(2026, 3, 4), datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)),
            ("unix_int", 1443651141, datetime(2015, 9, 30, 22, 12, 21, tzinfo=UTC)),
            ("iso_z_suffix", "2021-08-31T13:43:35.000000Z", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
            ("iso_offset", "2021-08-31T13:43:35+00:00", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected


class TestActivityDateWindow:
    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_first_sync_uses_lookback_window(self) -> None:
        window = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=None, lookback_days=30
        )
        assert window.end - window.start == 30 * 24 * 60 * 60
        assert window.end == int(datetime(2026, 6, 23, tzinfo=UTC).timestamp())

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_full_refresh_uses_lookback_window(self) -> None:
        # Activity requires a date window even without an incremental cursor, so a full refresh still
        # falls back to the lookback window rather than omitting the bounds.
        window = _activity_date_window(
            should_use_incremental_field=False, db_incremental_field_last_value=None, lookback_days=30
        )
        assert window.end - window.start == 30 * 24 * 60 * 60

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_incremental_starts_from_last_value(self) -> None:
        last = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)
        window = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=last, lookback_days=30
        )
        assert window.start == int(last.timestamp())
        assert window.end == int(datetime(2026, 6, 23, tzinfo=UTC).timestamp())

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_cursor_older_than_the_tier_is_clamped(self) -> None:
        # A watermark left behind by a paused sync asks for more history than the plan retains,
        # which MailerSend rejects; it must be clamped to the tier being tried.
        stale = datetime(2026, 1, 1, tzinfo=UTC)
        window = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=stale, lookback_days=7
        )
        assert window.end - window.start == 7 * 24 * 60 * 60

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_future_cursor_is_clamped_below_date_to(self) -> None:
        # A future-dated cursor would make date_from >= date_to and 422 the request; it must be clamped.
        future = datetime(2027, 1, 1, tzinfo=UTC)
        window = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=future, lookback_days=30
        )
        assert window.start < window.end


class TestCheckCredentials:
    @staticmethod
    def _session_returning(status_code: int) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        return session

    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_ok"),
        [
            (200, None, True),
            (401, None, False),
            (403, None, True),  # valid token, missing scope — accepted at source-create
            (403, "activity", False),  # scope gap surfaced for a specific schema
            (500, None, False),
        ],
    )
    def test_status_mapping(
        self, status_code: int, schema_name: str | None, expected_ok: bool, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(mailersend, "make_tracked_session", lambda *a, **k: self._session_returning(status_code))
        ok, _error = check_credentials("mlsn.token", schema_name)
        assert ok is expected_ok

    def test_network_error_is_not_valid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(mailersend, "make_tracked_session", lambda *a, **k: session)
        ok, error = check_credentials("mlsn.token")
        assert ok is False
        assert error is not None


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "d1", "name": "a.com"}, {"id": "d2", "name": "b.com"}])])
        rows = _rows(_source("domains", _make_manager()))
        assert [r["id"] for r in rows] == ["d1", "d2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_links_next_is_null(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "r1"}], next_url=f"{BASE}/recipients?page=2&limit=100"),
                _page([{"id": "r2"}], next_url=None),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("recipients", manager))

        assert [r["id"] for r in rows] == ["r1", "r2"]
        # Second request follows the body's next link verbatim.
        assert snaps[1]["url"] == f"{BASE}/recipients?page=2&limit=100"
        # A checkpoint is saved after the first page (more remain) and points at the next link.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == MailerSendResumeConfig(
            fanout_state={"next_url": f"{BASE}/recipients?page=2&limit=100"}
        )

    @parameterized.expand(
        [
            ("last_allowed_page_is_followed", 1000, 2, ["r1", "r2"]),
            ("page_past_the_cap_ends_the_table", 1001, 1, ["r1"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_the_documented_page_cap(
        self,
        _name: str,
        next_page: int,
        expected_requests: int,
        expected_ids: list[str],
        MockSession: MagicMock,
    ) -> None:
        # MailerSend accepts pages 1-1000 and rejects page 1001 with a 422, but still advertises a
        # next link on page 1000, so the cap has to end the table instead of following that link.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "r1"}], next_url=f"{BASE}/recipients?page={next_page}&limit=100"),
                _page([{"id": "r2"}], next_url=None),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("recipients", manager))

        assert [r["id"] for r in rows] == expected_ids
        assert session.send.call_count == expected_requests

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_checkpoint(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], next_url=None)])
        manager = _make_manager()
        rows = _rows(_source("templates", manager))
        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession: MagicMock) -> None:
        # A saved state must skip already-synced earlier pages and resume at the saved next link.
        session = MockSession.return_value
        next_url = f"{BASE}/messages?page=2&limit=100"
        snaps = _wire(session, [_page([{"id": "m2"}], next_url=None)])

        manager = _make_manager(MailerSendResumeConfig(fanout_state={"next_url": next_url}))
        rows = _rows(_source("messages", manager))

        assert [r["id"] for r in rows] == ["m2"]
        assert snaps[0]["url"] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_limit_param_sent(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "d1"}])])
        _rows(_source("domains", _make_manager()))
        assert snaps[0]["limit"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offhost_links_next_rejected_before_send(self, MockSession: MagicMock) -> None:
        # `links.next` is followed verbatim, so an off-host value must be rejected by the client's
        # host pin before the Bearer token can be replayed to an attacker-controlled host.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "r1"}], next_url="https://evil.example/v1/recipients?page=2"),
                _page([{"id": "r2"}], next_url=None),
            ],
        )

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("recipients", _make_manager()))

        # Only the on-host first page went out; the off-host next link never reached the network.
        assert session.send.call_count == 1


class TestActivityFanOut:
    @staticmethod
    def _domains(*ids: str) -> Response:
        return _page([{"id": i} for i in ids], next_url=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_domains_and_stamps_domain_id(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                self._domains("d1", "d2"),
                _page([{"id": "a1", "type": "sent"}], next_url=None),
                _page([{"id": "a2", "type": "opened"}], next_url=None),
            ],
        )
        rows = _rows(
            _source(
                "activity",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        assert rows == [
            {"id": "a1", "type": "sent", "domain_id": "d1"},
            {"id": "a2", "type": "opened", "domain_id": "d2"},
        ]

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_required_date_window_params(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [self._domains("d1"), _page([{"id": "a1"}], next_url=None)])

        _rows(
            _source(
                "activity",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )

        activity_call = next(c for c in snaps if "/activity/" in c["url"])
        assert activity_call["url"] == f"{BASE}/activity/d1"
        assert activity_call["date_from"] == int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        assert "date_to" in activity_call

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_domain(self, MockSession: MagicMock) -> None:
        # State marking d1 complete must skip it and only fetch d2.
        session = MockSession.return_value
        snaps = _wire(
            session,
            [self._domains("d1", "d2"), _page([{"id": "a2"}], next_url=None)],
        )
        manager = _make_manager(
            MailerSendResumeConfig(fanout_state={"completed": ["/activity/d1"], "current": None, "child_state": None})
        )
        rows = _rows(
            _source(
                "activity",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        assert [r["id"] for r in rows] == ["a2"]
        assert [c["url"] for c in snaps if "/activity/" in c["url"]] == [f"{BASE}/activity/d2"]

    @staticmethod
    def _rejected_window() -> Response:
        # MailerSend rejects a window reaching past the account's activity retention.
        return _response({"message": "The given data was invalid."}, status_code=422)

    @staticmethod
    def _window_days(snapshot: dict[str, Any]) -> float:
        return (snapshot["date_to"] - snapshot["date_from"]) / (24 * 60 * 60)

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_narrows_the_window_when_the_account_retains_less(self, MockSession: MagicMock) -> None:
        # Activity retention is 30, 7 or 1 days depending on the plan and no endpoint reports it,
        # so a rejected window must step down a tier rather than fail the whole sync.
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                _page([{"id": "a1"}], next_url=None),
            ],
        )

        rows = _rows(_source("activity", _make_manager()))

        assert [r["id"] for r in rows] == ["a1"]
        attempts = [c for c in snaps if "/activity/" in c["url"]]
        assert [self._window_days(a) for a in attempts] == [30, 7]

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_tier_rejected_fails_the_sync(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                self._rejected_window(),
                self._domains("d1"),
                self._rejected_window(),
            ],
        )

        with pytest.raises(HTTPError):
            _rows(_source("activity", _make_manager()))

        attempts = [c for c in snaps if "/activity/" in c["url"]]
        assert [self._window_days(a) for a in attempts] == [30, 7, 1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_all_rows_yielded_for_small_domains(self, MockSession: MagicMock) -> None:
        # Every domain's rows are yielded even when each domain is smaller than a page.
        session = MockSession.return_value
        _wire(
            session,
            [
                self._domains("d1", "d2"),
                _page([{"id": "a1"}], next_url=None),
                _page([{"id": "a2"}], next_url=None),
            ],
        )
        rows = _rows(
            _source(
                "activity",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        assert [r["id"] for r in rows] == ["a1", "a2"]


class TestLegacyResumeStateCompat:
    def test_legacy_state_shape_still_deserializes(self) -> None:
        # Resume state saved by the pre-migration source (next_page/domain_id only) must still parse.
        state = MailerSendResumeConfig(next_page=3, domain_id="d2")
        assert state.next_page == 3
        assert state.domain_id == "d2"
        assert state.fanout_state is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_only_state_starts_fresh(self, MockSession: MagicMock) -> None:
        # With no fanout_state, the run starts from the first page rather than a stale legacy cursor.
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "d1"}], next_url=None)])
        manager = _make_manager(MailerSendResumeConfig(next_page=5, domain_id=None))
        _rows(_source("domains", manager))
        assert snaps[0]["url"] == f"{BASE}/domains"


class TestSourceResponseShape:
    @parameterized.expand(["domains", "recipients", "templates", "messages", "activity"])
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        resource = _source(endpoint, _make_manager())
        assert resource.name == endpoint
        assert resource.primary_keys == MAILERSEND_ENDPOINTS[endpoint].primary_keys

    def test_activity_primary_key_includes_domain_id(self) -> None:
        # Activity ids are only unique within a domain, so the table-wide key must include domain_id.
        assert MAILERSEND_ENDPOINTS["activity"].primary_keys == ["domain_id", "id"]

    @parameterized.expand([("activity", "desc"), ("domains", "asc")])
    def test_sort_mode(self, endpoint: str, expected_sort: str) -> None:
        assert _source(endpoint, _make_manager()).sort_mode == expected_sort

    @parameterized.expand(["domains", "recipients", "templates", "messages", "activity"])
    def test_partitions_on_created_at(self, endpoint: str) -> None:
        resource = _source(endpoint, _make_manager())
        assert resource.partition_keys == ["created_at"]
        assert resource.partition_mode == "datetime"
