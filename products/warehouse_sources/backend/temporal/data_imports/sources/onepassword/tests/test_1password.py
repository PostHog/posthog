import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword import onepassword
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword import (
    OnePasswordResumeConfig,
    _initial_start_time,
    get_base_url,
    introspect,
    onepassword_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ONEPASSWORD_ENDPOINTS

# onepassword_source builds its (capture-disabled) session via make_tracked_session in the
# onepassword module and hands it to the RESTClient, so patch it there.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword.make_tracked_session"
)


def _response(payload: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = "OK" if status < 400 else "Unauthorized"
    resp.url = "https://events.1password.com/api/v2/auditevents"
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: OnePasswordResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's POST body AT SEND TIME.

    The paginator rewrites ``request.json`` in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared object after the run.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run_source(
    responses: list[Response],
    manager: mock.MagicMock,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with mock.patch(SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        bodies = _wire(session, responses)
        source_response = onepassword_source(
            region="us",
            api_token="token",
            endpoint="audit_events",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            **kwargs,
        )
        rows = _rows(source_response)
    return rows, bodies


class TestRegionMapping:
    @parameterized.expand(
        [
            ("us", "https://events.1password.com"),
            ("ca", "https://events.1password.ca"),
            ("eu", "https://events.1password.eu"),
            ("enterprise", "https://events.ent.1password.com"),
        ]
    )
    def test_region_maps_to_host(self, region: str, expected: str) -> None:
        assert get_base_url(region) == expected

    def test_unknown_region_raises(self) -> None:
        # The bearer token must only ever be sent to a 1Password-owned host; an unmapped region
        # value must fail instead of building a URL from it.
        with pytest.raises(ValueError):
            get_base_url("attacker.example.com")


class TestInitialStartTime:
    @parameterized.expand(
        [
            # ResetCursor's start_time defaults to one hour ago server-side, so a first sync that
            # omitted it (or sent nothing on full refresh) would silently drop all history.
            ("first_sync_uses_default_lookback", False, None, "2025-07-15T12:00:00+00:00"),
            ("full_refresh_ignores_watermark", False, "2026-07-01T00:00:00Z", "2025-07-15T12:00:00+00:00"),
            (
                "incremental_uses_datetime_watermark",
                True,
                datetime(2026, 7, 1, tzinfo=UTC),
                "2026-07-01T00:00:00+00:00",
            ),
            ("incremental_uses_date_watermark", True, date(2026, 7, 1), "2026-07-01T00:00:00+00:00"),
            ("incremental_passes_string_watermark", True, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ]
    )
    def test_initial_start_time(self, _name: str, use_incremental: bool, watermark: Any, expected: str) -> None:
        with freeze_time("2026-07-15T12:00:00Z"):
            assert _initial_start_time(use_incremental, watermark) == expected


class TestPagination:
    def test_pagination_follows_cursor_until_has_more_is_false(self) -> None:
        responses = [
            _response({"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}, {"uuid": "b"}]}),
            _response({"cursor": "c2", "has_more": False, "items": [{"uuid": "c"}]}),
        ]
        rows, bodies = _run_source(responses, _make_manager())

        assert [r["uuid"] for r in rows] == ["a", "b", "c"]
        # First request is a ResetCursor; every subsequent request must carry only the cursor —
        # resending the ResetCursor would restart the stream from start_time on every page.
        assert bodies[0] == {"limit": onepassword.PAGE_LIMIT, "start_time": bodies[0]["start_time"]}
        assert bodies[1] == {"cursor": "c1"}

    def test_incremental_reset_cursor_starts_from_watermark(self) -> None:
        responses = [_response({"cursor": "c1", "has_more": False, "items": [{"uuid": "a"}]})]
        _, bodies = _run_source(
            responses,
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
        )
        assert bodies[0] == {"limit": onepassword.PAGE_LIMIT, "start_time": "2026-07-01T00:00:00Z"}

    def test_state_is_saved_after_each_yielded_page(self) -> None:
        # A crash while the pipeline holds a batch must re-enter BEFORE it (merge dedupes on uuid),
        # so state is saved only AFTER a page is yielded, and it points at the next page's cursor.
        responses = [
            _response({"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}]}),
            _response({"cursor": "c2", "has_more": False, "items": [{"uuid": "b"}]}),
        ]
        manager = _make_manager()
        with mock.patch(SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, responses)
            batches = onepassword_source(
                region="us",
                api_token="token",
                endpoint="audit_events",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
            ).items()

            it = iter(cast("Iterable[Any]", batches))
            first = next(it)
            assert first == [{"uuid": "a"}]
            # Nothing saved before the batch is handed to the consumer.
            manager.save_state.assert_not_called()

            assert [r["uuid"] for r in next(it)] == ["b"]
            assert next(it, None) is None

        # The next-page cursor c1 is persisted after page 1 yields; the terminal page (has_more
        # false) leaves nothing more to resume from.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [OnePasswordResumeConfig(cursor="c1")]

    def test_resume_posts_saved_cursor_instead_of_reset_cursor(self) -> None:
        # Sending a ResetCursor on resume would re-walk the stream from start_time, re-paying the
        # whole backfill after every heartbeat timeout.
        responses = [_response({"cursor": "c9", "has_more": False, "items": [{"uuid": "z"}]})]
        manager = _make_manager(OnePasswordResumeConfig(cursor="c8"))
        rows, bodies = _run_source(responses, manager)
        assert bodies == [{"cursor": "c8"}]
        assert [r["uuid"] for r in rows] == ["z"]

    def test_empty_page_with_stale_cursor_terminates(self) -> None:
        # Defensive guard: has_more=true with no items and a cursor that never advances would
        # otherwise loop forever against the API.
        responses = [
            _response({"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}]}),
            _response({"cursor": "c1", "has_more": True, "items": []}),
        ]
        rows, bodies = _run_source(responses, _make_manager())
        assert [r["uuid"] for r in rows] == ["a"]
        assert len(bodies) == 2

    def test_empty_page_with_advancing_cursor_continues(self) -> None:
        # An empty page whose cursor advanced is progress (the API can skip ahead); only a stale
        # cursor means stuck.
        responses = [
            _response({"cursor": "c1", "has_more": True, "items": []}),
            _response({"cursor": "c2", "has_more": False, "items": [{"uuid": "a"}]}),
        ]
        rows, bodies = _run_source(responses, _make_manager())
        assert [r["uuid"] for r in rows] == ["a"]
        assert bodies[1] == {"cursor": "c1"}


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        responses = [_response({}, status=status), _response({"has_more": False, "items": []})]
        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_a, **_k: None):  # type: ignore[attr-defined]
            with mock.patch(SESSION_PATCH) as MockSession:
                session = MockSession.return_value
                _wire(session, responses)
                rows = _rows(
                    onepassword_source(
                        region="us",
                        api_token="token",
                        endpoint="audit_events",
                        team_id=1,
                        job_id="job-1",
                        resumable_source_manager=_make_manager(),
                    )
                )
        assert rows == []
        assert session.send.call_count == 2

    def test_unauthorized_raises_without_retry(self) -> None:
        # Retrying a 401 can never succeed; it must surface immediately so the job fails with the
        # non-retryable credential message instead of burning five attempts.
        with mock.patch(SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, [_response({"Error": {"Message": "Unauthorized"}}, status=401)])
            with pytest.raises(HTTPError):
                _rows(
                    onepassword_source(
                        region="us",
                        api_token="token",
                        endpoint="audit_events",
                        team_id=1,
                        job_id="job-1",
                        resumable_source_manager=_make_manager(),
                    )
                )
            assert session.send.call_count == 1


class TestIntrospect:
    @parameterized.expand(
        [
            ("valid", 200, {"features": ["auditevents"]}, {"features": ["auditevents"]}),
            ("unauthorized", 401, {"Error": {"Message": "Unauthorized"}}, None),
            ("server_error", 500, {}, None),
        ]
    )
    def test_status_maps_to_result(self, _name: str, status: int, payload: dict, expected: dict | None) -> None:
        response = MagicMock(status_code=status)
        response.json.return_value = payload
        session = MagicMock()
        session.get.return_value = response
        with mock.patch.object(onepassword, "make_tracked_session", return_value=session):
            assert introspect("us", "token") == expected

    def test_network_error_returns_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(onepassword, "make_tracked_session", return_value=session):
            assert introspect("us", "token") is None


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ONEPASSWORD_ENDPOINTS])
    def test_response_shape(self, endpoint: str) -> None:
        # Ordering of the cursor stream is not documented, so "desc" is required: it defers the
        # watermark to successful job end, which is safe for any arrival order. Flipping to "asc"
        # per-batch checkpointing could advance the watermark past unseen older events.
        with mock.patch(SESSION_PATCH):
            response = onepassword_source(
                region="us",
                api_token="token",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )
        assert response.name == endpoint
        assert response.sort_mode == "desc"
        assert response.primary_keys == ["uuid"]
        assert response.partition_keys == ["timestamp"]
        assert response.partition_mode == "datetime"
