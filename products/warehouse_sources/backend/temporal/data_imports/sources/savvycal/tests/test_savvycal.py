import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal import (
    SAVVYCAL_BASE_URL,
    SavvyCalResumeConfig,
    savvycal_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import (
    ENDPOINTS,
    SAVVYCAL_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the savvycal module.
SAVVYCAL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal.make_tracked_session"
)
# The client's retry backoff sleeps on tenacity's nap; patch it so retry-path tests don't wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(entries: Optional[list[dict[str, Any]]], after: Optional[str] = None, *, status: int = 200) -> Response:
    """A SavvyCal list response: {"entries": [...], "metadata": {"after": ...}}."""
    payload = {"entries": entries or [], "metadata": {"after": after, "before": None, "limit": 100}}
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(payload).encode()
    resp.url = f"{SAVVYCAL_BASE_URL}/events"
    return resp


def _raw_response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{SAVVYCAL_BASE_URL}/events"
    return resp


def _make_manager(resume_state: SavvyCalResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(
    session: mock.MagicMock,
    responses: list[Response],
    endpoint: str = "events",
    manager: mock.MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], mock.MagicMock]:
    params = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    source_response = savvycal_source(
        api_key="pt_secret_key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )
    rows = [row for page in cast("Iterable[Any]", source_response.items()) for row in page]
    return rows, params, manager


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        rows, params, manager = _run(session, [_response([{"id": "a"}, {"id": "b"}], after=None)])
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A null after cursor ends the sync without persisting resume state.
        manager.save_state.assert_not_called()
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_after_cursor_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        rows, params, manager = _run(
            session, [_response([{"id": "a"}], after="cur_2"), _response([{"id": "b"}], after=None)]
        )
        assert rows == [{"id": "a"}, {"id": "b"}]
        # The first request carries no after param; the second carries the cursor from page one.
        assert "after" not in params[0]
        assert params[1]["after"] == "cur_2"
        # State is saved exactly once — after the first page, pointing at the next cursor.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == SavvyCalResumeConfig(after="cur_2", from_date=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        manager = _make_manager(SavvyCalResumeConfig(after="cur_2"))
        # The first page must never be fetched on resume; the seeded cursor rides on the first request.
        rows, params, _ = _run(session, [_response([{"id": "b"}], after=None)], manager=manager)
        assert rows == [{"id": "b"}]
        assert params[0]["after"] == "cur_2"
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        rows, _, manager = _run(session, [_response([], after=None)])
        assert rows == []
        manager.save_state.assert_not_called()


class TestEventFilters:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_full_refresh_widens_default_filters(self, MockSession) -> None:
        # SavvyCal defaults to period=upcoming, state=confirmed, attendance=attending — any of those
        # silently drops most of the account's history from a warehouse import.
        session = MockSession.return_value
        _, params, _ = _run(session, [_response([], after=None)])
        assert params[0]["period"] == "all"
        assert params[0]["state"] == "all"
        assert params[0]["attendance"] == "any"
        assert params[0]["direction"] == "asc"
        assert params[0]["limit"] == 100
        assert "from" not in params[0]

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 5, 14, 30, tzinfo=UTC), "2026-03-05"),
            ("date", date(2026, 3, 5), "2026-03-05"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_maps_watermark_to_fixed_window(
        self, _name: str, watermark: Any, expected_from: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _, params, _ = _run(
            session,
            [_response([], after=None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        assert params[0]["period"] == "fixed"
        assert params[0]["from"] == expected_from

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_reuses_saved_from_bound_over_new_watermark(self, MockSession) -> None:
        # The saved cursor was minted under the original `from` bound; recomputing it from an
        # advanced watermark would pair the cursor with a different query.
        session = MockSession.return_value
        manager = _make_manager(SavvyCalResumeConfig(after="cur_2", from_date="2026-01-01"))
        _, params, _ = _run(
            session,
            [_response([{"id": "b"}], after="cur_3"), _response([], after=None)],
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert all(p["from"] == "2026-01-01" for p in params)
        # The re-saved state carries the same original bound forward.
        assert manager.save_state.call_args.args[0].from_date == "2026-01-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_events_endpoint_sends_no_event_filters(self, MockSession) -> None:
        session = MockSession.return_value
        _, params, _ = _run(session, [_response([], after=None)], endpoint="links")
        assert params[0] == {"limit": 100}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_flag_ignored_for_full_refresh_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _, params, _ = _run(
            session,
            [_response([], after=None)],
            endpoint="webhooks",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert "from" not in params[0]
        assert "period" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_webhooks_secret_is_redacted(self, MockSession) -> None:
        # The webhook signing secret must never reach the warehouse table.
        session = MockSession.return_value
        rows, _, _ = _run(
            session,
            [_response([{"id": "wbhk_1", "url": "https://x", "secret": "whsec_leak"}], after=None)],
            endpoint="webhooks",
        )
        assert rows == [{"id": "wbhk_1", "url": "https://x"}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_and_recovers(self, _name: str, status: int, MockSession, _sleep) -> None:
        # A 429/5xx is retried by the client; a following good page completes the sync.
        session = MockSession.return_value
        rows, _, _ = _run(session, [_response(None, status=status), _response([{"id": "a"}], after=None)])
        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("bad_request", 400)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_and_does_not_retry(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        with pytest.raises(HTTPError):
            _run(session, [_response(None, status=status)])
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("bare_list", [{"id": "a"}]),
            ("missing_entries", {"metadata": {"after": None}}),
            ("entries_not_a_list", {"entries": {"id": "a"}, "metadata": {"after": None}}),
        ]
    )
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_200_payload_is_retried_and_recovers(
        self, _name: str, malformed_body: Any, MockSession, _sleep
    ) -> None:
        # A 200 whose body isn't the {"entries": [...]} shape is treated as transient and retried.
        session = MockSession.return_value
        rows, _, _ = _run(session, [_raw_response(malformed_body), _response([{"id": "a"}], after=None)])
        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
            ("unauthorized", 401, (False, "Invalid SavvyCal personal access token")),
            ("forbidden", 403, (False, "Invalid SavvyCal personal access token")),
            ("server_error", 500, (False, "SavvyCal returned HTTP 500")),
        ]
    )
    @mock.patch(SAVVYCAL_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None], mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("pt_secret_key") == expected

    @mock.patch(SAVVYCAL_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        valid, message = validate_credentials("pt_secret_key")
        assert valid is False
        assert message == "Could not validate SavvyCal personal access token"


class TestSavvyCalSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = savvycal_source(
            api_key="pt_secret_key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    def test_events_partition_on_stable_created_at(self) -> None:
        response = savvycal_source(
            api_key="pt_secret_key",
            endpoint="events",
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        # start_at moves on reschedule; partitioning must stay on the immutable creation timestamp.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_links_have_no_partitioning(self) -> None:
        # The Link schema exposes no creation timestamp to partition on.
        response = savvycal_source(
            api_key="pt_secret_key",
            endpoint="links",
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SAVVYCAL_ENDPOINTS.values())
        assert set(SAVVYCAL_ENDPOINTS) == set(ENDPOINTS)
