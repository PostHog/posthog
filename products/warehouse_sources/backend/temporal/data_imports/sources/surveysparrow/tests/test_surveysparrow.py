import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow import (
    SurveySparrowResumeConfig,
    _format_cutoff,
    surveysparrow_source,
    validate_credentials,
)

BASE_URL = "https://api.surveysparrow.com"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the surveysparrow module.
SURVEYSPARROW_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow.make_tracked_session"
)


def _page(items: list[dict[str, Any]] | None, *, has_next_page: bool | None = None, status_code: int = 200) -> Response:
    body: dict[str, Any] = {"data": items or []}
    if has_next_page is not None:
        body["has_next_page"] = has_next_page
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _raw(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SurveySparrowResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return surveysparrow_source(
        "token",
        BASE_URL,
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFormatCutoff:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_floors_watermark_to_day(self, value: object, expected: str) -> None:
        assert _format_cutoff(value) == expected


class TestTopLevel:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_checkpoints_next_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 1}], has_next_page=True),
                _page([{"id": 2}], has_next_page=False),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("surveys", manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert [s["params"]["page"] for s in snaps] == [1, 2]
        assert [s["params"]["limit"] for s in snaps] == [100, 100]
        # Checkpoint once, pointing at the NEXT page (page 2); the last page saves nothing.
        saved = [c.args[0].paginator_state for c in manager.save_state.call_args_list]
        assert saved == [{"page": 2}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_despite_stale_flag(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], has_next_page=True)])
        manager = _make_manager()

        rows = _rows(_source("surveys", manager))

        assert rows == []
        assert session.send.call_count == 1


class TestFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cutoff_applied_to_children_but_not_survey_enumeration(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
            ],
        )

        _rows(
            _source(
                "responses",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        assert "date.gte" not in snaps[0]["params"]  # survey enumeration
        child = next(s for s in snaps if "/v3/responses" in s["url"])
        assert child["params"]["date.gte"] == "2026-01-02"


class TestRetry:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_exhaust_then_raise(self, MockSession, status_code, monkeypatch) -> None:
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
        session = MockSession.return_value
        _wire(session, [_page([], has_next_page=False, status_code=status_code) for _ in range(5)])

        with pytest.raises(Exception):
            _rows(_source("surveys", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_is_not_retried(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], has_next_page=False, status_code=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("surveys", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(SURVEYSPARROW_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_ok) -> None:
        mock_session.return_value.get.return_value = _raw({}, status_code=status_code)

        ok, error = validate_credentials("token", BASE_URL)

        assert ok is expected_ok
        if not ok:
            assert error
        url = mock_session.return_value.get.call_args.args[0]
        assert url == f"{BASE_URL}/v3/surveys"

    @mock.patch(SURVEYSPARROW_SESSION_PATCH)
    def test_request_exception_is_failure(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        ok, error = validate_credentials("token", BASE_URL)

        assert ok is False
        assert error

    @mock.patch(SURVEYSPARROW_SESSION_PATCH)
    def test_token_is_declared_redactable(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _raw({}, status_code=200)

        validate_credentials("secret-token", BASE_URL)

        assert mock_session.call_args.kwargs.get("redact_values") == ("secret-token",)


class TestResumeConfigCompatibility:
    def test_legacy_saved_state_still_parses(self) -> None:
        # A checkpoint written by the pre-framework code must still deserialize via dataclass(**saved).
        cfg = SurveySparrowResumeConfig(**cast("dict[str, Any]", {"page": 4, "remaining_survey_ids": [20]}))
        assert cfg.page == 4
        assert cfg.remaining_survey_ids == [20]
        assert cfg.paginator_state is None
        assert cfg.fanout_state is None
