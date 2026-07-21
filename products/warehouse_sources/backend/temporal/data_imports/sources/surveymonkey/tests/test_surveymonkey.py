import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey import (
    SurveyMonkeyResumeConfig,
    _cutoff_param_name,
    _explode_questions,
    _format_incremental_value,
    _incremental_config,
    _promote_survey_id,
    surveymonkey_source,
    validate_credentials,
)

BASE_URL = "https://api.surveymonkey.com/v3"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the surveymonkey module.
SURVEYMONKEY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey.make_tracked_session"
)


def _page(items: list[dict[str, Any]] | None, *, next_url: str | None = None, status_code: int = 200) -> Response:
    body: dict[str, Any] = {"data": items or [], "links": {}}
    if next_url is not None:
        body["links"]["next"] = next_url
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _raw(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SurveyMonkeyResumeConfig | None = None) -> mock.MagicMock:
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
    incremental_field: str | None = None,
):
    return surveymonkey_source(
        "token",
        BASE_URL,
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("cursor-value", "cursor-value"),
        ],
    )
    def test_format(self, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result and "Z" not in result


class TestCutoffParamName:
    @pytest.mark.parametrize(
        "incremental_field, default, expected",
        [
            ("date_modified", "date_modified", "start_modified_at"),
            ("date_created", "date_modified", "start_created_at"),
            (None, "date_modified", "start_modified_at"),
        ],
    )
    def test_param_name(self, incremental_field: str | None, default: str, expected: str) -> None:
        assert _cutoff_param_name(incremental_field, default) == expected


class TestIncrementalConfig:
    def test_none_when_no_cursor_value(self) -> None:
        assert _incremental_config("surveys", True, None, None) is None

    def test_none_when_not_incremental_endpoint(self) -> None:
        # survey_pages has no incremental fields, so no server-side filter is ever injected.
        assert _incremental_config("survey_pages", True, datetime(2026, 1, 1), None) is None

    def test_surveys_uses_modified_filter(self) -> None:
        cfg = _incremental_config("surveys", True, datetime(2026, 1, 1), None)
        assert cfg is not None
        assert cfg["start_param"] == "start_modified_at"
        assert cfg["cursor_path"] == "date_modified"

    def test_responses_honours_created_field(self) -> None:
        cfg = _incremental_config("survey_responses", True, datetime(2026, 1, 1), "date_created")
        assert cfg is not None
        assert cfg["start_param"] == "start_created_at"
        assert cfg["cursor_path"] == "date_created"


class TestPromoteSurveyId:
    def test_renames_parent_id(self) -> None:
        assert _promote_survey_id({"id": "p1", "_surveys_id": "10"}) == {"id": "p1", "survey_id": "10"}

    def test_noop_without_parent_id(self) -> None:
        assert _promote_survey_id({"id": "p1"}) == {"id": "p1"}


class TestExplodeQuestions:
    def test_flattens_page_questions_with_parents(self) -> None:
        page = {"id": "pg1", "_surveys_id": "10", "questions": [{"id": "q1"}, {"id": "q2"}]}
        rows = _explode_questions(page)
        assert [r["id"] for r in rows] == ["q1", "q2"]
        assert all(r["survey_id"] == "10" and r["page_id"] == "pg1" for r in rows)

    def test_empty_questions_drops_page(self) -> None:
        assert _explode_questions({"id": "pg3", "_surveys_id": "10", "questions": []}) == []

    def test_missing_questions_key_drops_page(self) -> None:
        assert _explode_questions({"id": "pg3", "_surveys_id": "10"}) == []


class TestSurveysTopLevel:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_links_next(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "1"}], next_url=f"{BASE_URL}/surveys?page=2"),
                _page([{"id": "2"}]),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("surveys", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        # Page 1 carries the static list params; the next-page link is self-contained (params cleared).
        assert snaps[0]["url"] == f"{BASE_URL}/surveys"
        assert snaps[0]["params"]["per_page"] == 100
        assert "date_created" in snaps[0]["params"]["include"]
        assert snaps[0]["params"]["sort_by"] == "date_modified"
        assert snaps[0]["params"]["sort_order"] == "ASC"
        assert snaps[1]["url"] == f"{BASE_URL}/surveys?page=2"
        # Checkpoint once, pointing at the next page URL; the last page (no next) saves nothing.
        saved = [c.args[0].paginator_state for c in manager.save_state.call_args_list]
        assert saved == [{"next_url": f"{BASE_URL}/surveys?page=2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}])])
        manager = _make_manager()

        rows = _rows(_source("surveys", manager))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "99"}])])
        manager = _make_manager(SurveyMonkeyResumeConfig(paginator_state={"next_url": f"{BASE_URL}/surveys?page=7"}))

        rows = _rows(_source("surveys", manager))

        assert snaps[0]["url"] == f"{BASE_URL}/surveys?page=7"
        assert rows[0]["id"] == "99"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_applies_modified_cutoff_when_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "1"}])])
        manager = _make_manager()

        _rows(
            _source(
                "surveys",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert snaps[0]["params"]["start_modified_at"] == "2026-01-01T00:00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_cutoff_on_full_refresh(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "1"}])])

        _rows(_source("surveys", _make_manager()))

        assert "start_modified_at" not in snaps[0]["params"]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_surveys_and_injects_survey_id(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "10"}, {"id": "20"}]),  # /surveys list (one page)
                _page([{"id": "p1"}]),  # survey 10 pages
                _page([{"id": "p2"}]),  # survey 20 pages
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("survey_pages", manager))

        assert rows == [{"id": "p1", "survey_id": "10"}, {"id": "p2", "survey_id": "20"}]
        child_urls = [s["url"] for s in snaps if "/pages" in s["url"]]
        assert child_urls == [f"{BASE_URL}/surveys/10/pages", f"{BASE_URL}/surveys/20/pages"]
        # The survey enumeration is bare — no include/sort leaks into the parent listing.
        assert snaps[0]["url"] == f"{BASE_URL}/surveys"
        assert "include" not in snaps[0]["params"] and "sort_by" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_paginates_via_links_next(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "10"}]),  # /surveys list
                _page([{"id": "p1"}], next_url=f"{BASE_URL}/surveys/10/pages?page=2"),  # survey 10 page 1
                _page([{"id": "p2"}]),  # survey 10 page 2
            ],
        )

        rows = _rows(_source("survey_pages", _make_manager()))

        assert [r["id"] for r in rows] == ["p1", "p2"]
        assert all(r["survey_id"] == "10" for r in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_fan_out_skipping_completed_survey(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "10"}, {"id": "20"}]),  # /surveys relisted on resume
                _page([{"id": "p2"}]),  # survey 20 pages
            ],
        )
        manager = _make_manager(
            SurveyMonkeyResumeConfig(
                fanout_state={
                    "completed": ["/surveys/10/pages"],
                    "current": "/surveys/20/pages",
                    "child_state": None,
                }
            )
        )

        rows = _rows(_source("survey_pages", manager))

        # Survey 10 is already completed and never re-fetched; survey 20 is synced.
        assert rows == [{"id": "p2", "survey_id": "20"}]
        child_urls = [s["url"] for s in snaps if "/pages" in s["url"]]
        assert child_urls == [f"{BASE_URL}/surveys/20/pages"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_responses_apply_created_cutoff_and_no_sort(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "10"}]),  # /surveys list
                _page([{"id": "r1"}]),  # survey 10 responses
            ],
        )
        manager = _make_manager()

        rows = _rows(
            _source(
                "survey_responses",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="date_created",
            )
        )

        assert rows == [{"id": "r1", "survey_id": "10"}]
        child = next(s for s in snaps if "/responses/bulk" in s["url"])
        assert child["url"] == f"{BASE_URL}/surveys/10/responses/bulk"
        assert child["params"]["start_created_at"] == "2026-01-01T00:00:00"
        # responses/bulk has no server-side sort enum, so we don't send sort_by.
        assert "sort_by" not in child["params"]


class TestQuestions:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_explodes_questions_per_survey(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"id": "10"}]),  # /surveys list
                _raw(
                    {
                        "id": "10",
                        "pages": [
                            {"id": "pg1", "questions": [{"id": "q1"}, {"id": "q2"}]},
                            {"id": "pg2", "questions": [{"id": "q3"}]},
                            {"id": "pg3", "questions": []},
                        ],
                    }
                ),  # survey 10 details
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("survey_questions", manager))

        assert [r["id"] for r in rows] == ["q1", "q2", "q3"]
        assert all(r["survey_id"] == "10" for r in rows)
        assert [r["page_id"] for r in rows] == ["pg1", "pg1", "pg2"]
        assert snaps[-1]["url"] == f"{BASE_URL}/surveys/10/details"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_survey_without_pages_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "10"}]), _raw({"id": "10"})])

        rows = _rows(_source("survey_questions", _make_manager()))

        assert rows == []


class TestRetry:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_exhaust_then_raise(self, MockSession, status_code, monkeypatch) -> None:
        # Skip tenacity's real exponential-backoff sleeps while still exercising the full retry count.
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
        session = MockSession.return_value
        _wire(session, [_page([], status_code=status_code) for _ in range(5)])

        with pytest.raises(Exception):
            _rows(_source("surveys", _make_manager()))
        # 5 attempts total (the client default) before reraise.
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_is_not_retried(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], status_code=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("surveys", _make_manager()))
        # A 401 is permanent — issued exactly once, no retry.
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(SURVEYMONKEY_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_ok) -> None:
        body = {} if status_code == 200 else {"error": {"message": "nope"}}
        mock_session.return_value.get.return_value = _raw(body, status_code=status_code)

        ok, error = validate_credentials("token", BASE_URL)

        assert ok is expected_ok
        if not ok:
            assert error
        url = mock_session.return_value.get.call_args.args[0]
        assert url == f"{BASE_URL}/users/me"

    @mock.patch(SURVEYMONKEY_SESSION_PATCH)
    def test_request_exception_is_failure(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        ok, error = validate_credentials("token", BASE_URL)

        assert ok is False
        assert "boom" in (error or "")

    @mock.patch(SURVEYMONKEY_SESSION_PATCH)
    def test_token_is_declared_redactable(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _raw({}, status_code=200)

        validate_credentials("secret-token", BASE_URL)

        # The token must reach the tracked session's redaction set so it's scrubbed from errors/logs.
        assert mock_session.call_args.kwargs.get("redact_values") == ("secret-token",)


class TestResumeConfigCompatibility:
    def test_legacy_saved_state_still_parses(self) -> None:
        # A checkpoint written by the pre-framework code must still deserialize via dataclass(**saved).
        cfg = SurveyMonkeyResumeConfig(
            **cast("dict[str, Any]", {"next_url": f"{BASE_URL}/surveys?page=2", "remaining_survey_ids": ["10"]})
        )
        assert cfg.next_url == f"{BASE_URL}/surveys?page=2"
        assert cfg.remaining_survey_ids == ["10"]
        assert cfg.paginator_state is None
        assert cfg.fanout_state is None
