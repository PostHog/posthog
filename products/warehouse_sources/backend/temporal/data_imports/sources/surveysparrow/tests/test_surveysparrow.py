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
    _incremental_config,
    _stamp_survey_id,
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


class TestIncrementalConfig:
    def test_none_on_full_refresh(self) -> None:
        assert _incremental_config("responses", False, datetime(2026, 1, 1)) is None

    def test_none_without_cursor_value(self) -> None:
        assert _incremental_config("responses", True, None) is None

    def test_none_for_endpoint_without_server_filter(self) -> None:
        # questions has no cutoff_param, so no server-side date filter is ever injected.
        assert _incremental_config("questions", True, datetime(2026, 1, 1)) is None

    def test_responses_maps_to_date_gte(self) -> None:
        cfg = _incremental_config("responses", True, datetime(2026, 1, 1))
        assert cfg is not None
        assert cfg["start_param"] == "date.gte"
        assert cfg["cursor_path"] == "completed_time"


class TestStampSurveyId:
    def test_promotes_parent_id(self) -> None:
        assert _stamp_survey_id({"id": 7, "_surveys_id": 42}) == {"id": 7, "survey_id": 42}

    def test_noop_without_parent_id(self) -> None:
        assert _stamp_survey_id({"id": 7}) == {"id": 7}


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
    def test_missing_has_next_page_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}])])  # /v3/contact_lists omits the flag
        manager = _make_manager()

        rows = _rows(_source("contact_lists", manager))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_despite_stale_flag(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], has_next_page=True)])
        manager = _make_manager()

        rows = _rows(_source("surveys", manager))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_contacts_page_size_is_fifty(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": 1}], has_next_page=False)])

        _rows(_source("contacts", _make_manager()))

        assert snaps[0]["params"]["limit"] == 50

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": 99}], has_next_page=False)])
        manager = _make_manager(SurveySparrowResumeConfig(paginator_state={"page": 7}))

        rows = _rows(_source("surveys", manager))

        assert snaps[0]["params"]["page"] == 7
        assert rows[0]["id"] == 99


class TestFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_surveys_and_stamps_survey_id(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}, {"id": 20}], has_next_page=False),  # survey list
                _page([{"id": 1}], has_next_page=False),  # survey 10 responses
                _page([{"id": 2}], has_next_page=False),  # survey 20 responses
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("responses", manager))

        assert rows == [{"id": 1, "survey_id": 10}, {"id": 2, "survey_id": 20}]
        child_urls = [s["url"] for s in snaps if "/v3/responses" in s["url"]]
        assert child_urls == [
            f"{BASE_URL}/v3/responses?survey_id=10",
            f"{BASE_URL}/v3/responses?survey_id=20",
        ]
        # The survey enumeration is bare — no completed/order/cutoff params leak into it.
        assert snaps[0]["url"] == f"{BASE_URL}/v3/surveys"
        assert "state" not in snaps[0]["params"] and "date.gte" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_within_survey_then_advances_to_next(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}, {"id": 20}], has_next_page=False),  # survey list
                _page([{"id": 1}], has_next_page=True),  # survey 10 page 1
                _page([{"id": 2}], has_next_page=False),  # survey 10 page 2
                _page([{"id": 3}], has_next_page=False),  # survey 20 page 1
            ],
        )

        _rows(_source("responses", _make_manager()))

        child = [s for s in snaps if "/v3/responses" in s["url"]]
        assert [(s["url"], s["params"]["page"]) for s in child] == [
            (f"{BASE_URL}/v3/responses?survey_id=10", 1),
            (f"{BASE_URL}/v3/responses?survey_id=10", 2),
            (f"{BASE_URL}/v3/responses?survey_id=20", 1),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_responses_carry_completed_sort_params(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
            ],
        )

        _rows(_source("responses", _make_manager()))

        child = next(s for s in snaps if "/v3/responses" in s["url"])
        assert child["params"]["limit"] == 200
        assert child["params"]["state"] == "completed"
        assert child["params"]["order_by"] == "completedTime"
        assert child["params"]["order"] == "ASC"

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_questions_fan_out_without_cutoff(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}], has_next_page=False),
                _page([{"id": 5}], has_next_page=False),
            ],
        )

        rows = _rows(
            _source(
                "questions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert rows == [{"id": 5, "survey_id": 10}]
        child = next(s for s in snaps if "/v3/questions" in s["url"])
        assert "date.gte" not in child["params"]
        assert child["params"]["limit"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_fan_out_skipping_completed_survey(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": 10}, {"id": 20}], has_next_page=False),  # /v3/surveys relisted on resume
                _page([{"id": 2}], has_next_page=False),  # survey 20 responses
            ],
        )
        manager = _make_manager(
            SurveySparrowResumeConfig(
                fanout_state={
                    "completed": ["/v3/responses?survey_id=10"],
                    "current": "/v3/responses?survey_id=20",
                    "child_state": None,
                }
            )
        )

        rows = _rows(_source("responses", manager))

        # Survey 10 is already completed and never re-fetched; survey 20 is synced.
        assert rows == [{"id": 2, "survey_id": 20}]
        child_urls = [s["url"] for s in snaps if "/v3/responses" in s["url"]]
        assert child_urls == [f"{BASE_URL}/v3/responses?survey_id=20"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_surveys(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": 10}, {"id": 20}], has_next_page=False),
                _page([{"id": 1}], has_next_page=False),
                _page([{"id": 2}], has_next_page=False),
            ],
        )
        manager = _make_manager()

        _rows(_source("responses", manager))

        # Both surveys end up in the completed set as the fan-out finishes each one.
        completed = [c.args[0].fanout_state["completed"] for c in manager.save_state.call_args_list]
        assert ["/v3/responses?survey_id=10"] in completed
        assert sorted(["/v3/responses?survey_id=10", "/v3/responses?survey_id=20"]) in completed


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
