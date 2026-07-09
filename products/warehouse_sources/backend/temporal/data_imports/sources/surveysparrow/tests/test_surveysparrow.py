from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.settings import (
    SURVEYSPARROW_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow import (
    SurveySparrowResumeConfig,
    _attach_survey_id,
    _build_params,
    _format_cutoff,
    get_rows,
    validate_credentials,
)

BASE_URL = "https://api.surveysparrow.com"

PATCH_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow.make_tracked_session"
)


class _FakeSession:
    """Returns queued JSON responses in call order and records each request."""

    def __init__(self, responses: list[tuple[int, dict[str, Any]]]):
        self._responses = list(responses)
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> MagicMock:
        self.requests.append((url, params))
        status, payload = self._responses.pop(0)
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        response.json.return_value = payload
        response.text = ""
        if status >= 400:
            response.raise_for_status.side_effect = Exception(f"{status} error")
        return response


class _FakeManager:
    def __init__(self, state: SurveySparrowResumeConfig | None = None):
        self._state = state
        self.saved: list[SurveySparrowResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SurveySparrowResumeConfig | None:
        return self._state

    def save_state(self, data: SurveySparrowResumeConfig) -> None:
        self.saved.append(data)


def _patch_session(session: _FakeSession):
    return patch(PATCH_TARGET, lambda *args, **kwargs: session)


class TestFormatCutoff:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04", "2026-03-04"),
        ]
    )
    def test_floors_watermark_to_day(self, _name: str, value: object, expected: str) -> None:
        assert _format_cutoff(value) == expected


class TestBuildParams:
    def test_responses_carry_survey_id_cutoff_and_completed_sort(self) -> None:
        params = _build_params(SURVEYSPARROW_ENDPOINTS["responses"], page=3, cutoff="2026-01-01", survey_id=42)
        assert params["survey_id"] == 42
        assert params["date.gte"] == "2026-01-01"
        assert params["page"] == 3
        assert params["limit"] == 200
        assert params["state"] == "completed"
        assert params["order_by"] == "completedTime"
        assert params["order"] == "ASC"

    def test_cutoff_dropped_on_endpoints_without_server_filter(self) -> None:
        params = _build_params(SURVEYSPARROW_ENDPOINTS["questions"], page=1, cutoff="2026-01-01", survey_id=42)
        assert "date.gte" not in params
        assert params["survey_id"] == 42

    def test_surveys_have_no_survey_id_or_extra_params(self) -> None:
        params = _build_params(SURVEYSPARROW_ENDPOINTS["surveys"], page=1)
        assert params == {"limit": 100, "page": 1}


class TestAttachSurveyId:
    def test_stamps_survey_id_for_composite_key(self) -> None:
        assert _attach_survey_id({"id": 7}, 42) == {"id": 7, "survey_id": 42}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        session = _FakeSession([(status, {})])
        with _patch_session(session):
            ok, _error = validate_credentials("token", BASE_URL)
        assert ok is expected_ok
        assert session.requests[0][0] == f"{BASE_URL}/v3/surveys"


class TestGetRowsTopLevel:
    def test_paginates_and_checkpoints_each_page(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"has_next_page": True, "data": [{"id": 1}]}),
                (200, {"has_next_page": False, "data": [{"id": 2}]}),
            ]
        )
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "surveys", MagicMock(), manager))  # type: ignore[arg-type]

        assert [row["id"] for batch in batches for row in batch] == [1, 2]
        assert [params["page"] for _url, params in session.requests if params] == [1, 2]
        # Checkpoints point at the page just yielded, so a resume re-fetches (not skips) it.
        assert [state.page for state in manager.saved] == [1, 2]

    def test_missing_has_next_page_terminates(self) -> None:
        manager = _FakeManager()
        session = _FakeSession([(200, {"data": [{"id": 1}]})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "contact_lists", MagicMock(), manager))  # type: ignore[arg-type]

        assert len(session.requests) == 1
        assert batches == [[{"id": 1}]]

    def test_empty_page_terminates_despite_stale_flag(self) -> None:
        manager = _FakeManager()
        session = _FakeSession([(200, {"has_next_page": True, "data": []})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "surveys", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == []
        assert len(session.requests) == 1

    def test_resumes_from_saved_page(self) -> None:
        manager = _FakeManager(SurveySparrowResumeConfig(page=7))
        session = _FakeSession([(200, {"has_next_page": False, "data": [{"id": 99}]})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "surveys", MagicMock(), manager))  # type: ignore[arg-type]

        assert session.requests[0][1] is not None
        assert session.requests[0][1]["page"] == 7
        assert batches[0][0]["id"] == 99


class TestGetRowsFanout:
    def test_iterates_surveys_and_stamps_survey_id(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"has_next_page": False, "data": [{"id": 10}, {"id": 20}]}),  # survey list
                (200, {"has_next_page": False, "data": [{"id": 1}]}),  # survey 10 responses
                (200, {"has_next_page": False, "data": [{"id": 2}]}),  # survey 20 responses
            ]
        )
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "responses", MagicMock(), manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert rows == [{"id": 1, "survey_id": 10}, {"id": 2, "survey_id": 20}]
        child_requests = session.requests[1:]
        assert [params["survey_id"] for _url, params in child_requests if params] == [10, 20]

    def test_pages_within_survey_then_advances_to_next(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"has_next_page": False, "data": [{"id": 10}, {"id": 20}]}),  # survey list
                (200, {"has_next_page": True, "data": [{"id": 1}]}),  # survey 10 page 1
                (200, {"has_next_page": False, "data": [{"id": 2}]}),  # survey 10 page 2
                (200, {"has_next_page": False, "data": [{"id": 3}]}),  # survey 20 page 1
            ]
        )
        with _patch_session(session):
            list(get_rows("token", BASE_URL, "responses", MagicMock(), manager))  # type: ignore[arg-type]

        child_params = [params for _url, params in session.requests[1:] if params]
        assert [(p["survey_id"], p["page"]) for p in child_params] == [(10, 1), (10, 2), (20, 1)]

    def test_incremental_cutoff_applied_to_children_but_not_survey_enumeration(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"has_next_page": False, "data": [{"id": 10}]}),
                (200, {"has_next_page": False, "data": [{"id": 1}]}),
            ]
        )
        with _patch_session(session):
            list(
                get_rows(
                    "token",
                    BASE_URL,
                    "responses",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                )
            )

        survey_list_params = session.requests[0][1]
        child_params = session.requests[1][1]
        assert survey_list_params is not None and "date.gte" not in survey_list_params
        assert child_params is not None and child_params["date.gte"] == "2026-01-02"

    def test_resumes_remaining_surveys_without_relisting(self) -> None:
        manager = _FakeManager(SurveySparrowResumeConfig(page=4, remaining_survey_ids=[20]))
        session = _FakeSession([(200, {"has_next_page": False, "data": [{"id": 2}]})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "responses", MagicMock(), manager))  # type: ignore[arg-type]

        # No survey enumeration on resume; it goes straight to the saved survey and page.
        assert len(session.requests) == 1
        url, params = session.requests[0]
        assert url == f"{BASE_URL}/v3/responses"
        assert params is not None and params["survey_id"] == 20 and params["page"] == 4
        assert batches[0][0] == {"id": 2, "survey_id": 20}

    def test_checkpoints_current_survey_and_page(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"has_next_page": False, "data": [{"id": 10}, {"id": 20}]}),
                (200, {"has_next_page": False, "data": [{"id": 1}]}),
                (200, {"has_next_page": False, "data": [{"id": 2}]}),
            ]
        )
        with _patch_session(session):
            list(get_rows("token", BASE_URL, "responses", MagicMock(), manager))  # type: ignore[arg-type]

        assert [(state.remaining_survey_ids, state.page) for state in manager.saved] == [
            ([10, 20], 1),
            ([20], 1),
        ]
