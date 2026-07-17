from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import (
    SURVEYMONKEY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey import (
    SurveyMonkeyResumeConfig,
    _attach_survey_id,
    _build_list_url,
    _cutoff_param_name,
    _extract_questions,
    _format_incremental_value,
    get_rows,
    validate_credentials,
)

BASE_URL = "https://api.surveymonkey.com/v3"

PATCH_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey.make_tracked_session"
)


class _FakeSession:
    """Returns queued JSON responses in call order and records the URLs requested."""

    def __init__(self, responses: list[tuple[int, dict[str, Any]]]):
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> MagicMock:
        self.urls.append(url)
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
    def __init__(self, state: SurveyMonkeyResumeConfig | None = None):
        self._state = state
        self.saved: list[SurveyMonkeyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SurveyMonkeyResumeConfig | None:
        return self._state

    def save_state(self, data: SurveyMonkeyResumeConfig) -> None:
        self.saved.append(data)


def _patch_session(session: _FakeSession):
    return patch(PATCH_TARGET, lambda *args, **kwargs: session)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result and "Z" not in result


class TestCutoffParamName:
    @parameterized.expand(
        [
            ("modified_default", "date_modified", "start_modified_at"),
            ("created", "date_created", "start_created_at"),
            ("none_falls_back_to_default", None, "start_modified_at"),
        ]
    )
    def test_cutoff_param_name(self, _name: str, incremental_field: str | None, expected: str) -> None:
        config = SURVEYMONKEY_ENDPOINTS["survey_responses"]
        assert _cutoff_param_name(incremental_field, config) == expected


class TestBuildListUrl:
    def test_surveys_requests_include_sort_and_no_cutoff(self) -> None:
        url = _build_list_url(BASE_URL, SURVEYMONKEY_ENDPOINTS["surveys"], cutoff=None, incremental_field=None)
        assert url.startswith(f"{BASE_URL}/surveys?")
        assert "per_page=100" in url
        assert "include=" in url and "date_created" in url
        assert "sort_by=date_modified" in url
        assert "sort_order=ASC" in url
        assert "start_modified_at" not in url

    def test_surveys_applies_modified_cutoff(self) -> None:
        url = _build_list_url(
            BASE_URL, SURVEYMONKEY_ENDPOINTS["surveys"], cutoff="2026-01-01T00:00:00", incremental_field="date_modified"
        )
        assert "start_modified_at=2026-01-01T00%3A00%3A00" in url

    def test_responses_fanout_formats_survey_id_and_created_cutoff(self) -> None:
        url = _build_list_url(
            BASE_URL,
            SURVEYMONKEY_ENDPOINTS["survey_responses"],
            cutoff="2026-01-01T00:00:00",
            incremental_field="date_created",
            survey_id="42",
        )
        assert url.startswith(f"{BASE_URL}/surveys/42/responses/bulk?")
        assert "start_created_at=2026-01-01T00%3A00%3A00" in url
        # responses/bulk has no server-side sort enum, so we don't send sort_by.
        assert "sort_by" not in url


class TestAttachSurveyId:
    def test_sets_survey_id(self) -> None:
        assert _attach_survey_id({"id": "p1"}, "10") == {"id": "p1", "survey_id": "10"}


class TestExtractQuestions:
    def test_flattens_pages_and_questions_with_parents(self) -> None:
        details = {
            "id": "10",
            "pages": [
                {"id": "pg1", "questions": [{"id": "q1"}, {"id": "q2"}]},
                {"id": "pg2", "questions": [{"id": "q3"}]},
                {"id": "pg3", "questions": []},
            ],
        }
        rows = _extract_questions(details, "10")
        assert [r["id"] for r in rows] == ["q1", "q2", "q3"]
        assert all(r["survey_id"] == "10" for r in rows)
        assert rows[0]["page_id"] == "pg1"
        assert rows[2]["page_id"] == "pg2"

    def test_handles_missing_pages(self) -> None:
        assert _extract_questions({"id": "10"}, "10") == []


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
        assert session.urls == [f"{BASE_URL}/users/me"]


class TestGetRowsTopLevel:
    def test_paginates_and_checkpoints_each_page(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"data": [{"id": "1"}], "links": {"next": f"{BASE_URL}/surveys?page=2"}}),
                (200, {"data": [{"id": "2"}], "links": {}}),
            ]
        )
        with _patch_session(session):
            batches = list(
                get_rows("token", BASE_URL, "surveys", MagicMock(), manager)  # type: ignore[arg-type]
            )

        assert [row["id"] for batch in batches for row in batch] == ["1", "2"]
        # First checkpoint points at the initial page URL, not the next one.
        assert manager.saved[0].next_url == session.urls[0]
        assert len(manager.saved) == 2

    def test_resumes_from_saved_url(self) -> None:
        manager = _FakeManager(SurveyMonkeyResumeConfig(next_url=f"{BASE_URL}/surveys?page=7"))
        session = _FakeSession([(200, {"data": [{"id": "99"}], "links": {}})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "surveys", MagicMock(), manager))  # type: ignore[arg-type]

        assert session.urls == [f"{BASE_URL}/surveys?page=7"]
        assert batches[0][0]["id"] == "99"


class TestGetRowsFanout:
    def test_iterates_surveys_and_attaches_survey_id(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"data": [{"id": "10"}, {"id": "20"}], "links": {}}),  # survey list
                (200, {"data": [{"id": "p1"}], "links": {}}),  # survey 10 pages
                (200, {"data": [{"id": "p2"}], "links": {}}),  # survey 20 pages
            ]
        )
        with _patch_session(session):
            batches = list(
                get_rows("token", BASE_URL, "survey_pages", MagicMock(), manager)  # type: ignore[arg-type]
            )

        rows = [row for batch in batches for row in batch]
        assert rows == [{"id": "p1", "survey_id": "10"}, {"id": "p2", "survey_id": "20"}]

    def test_resumes_remaining_surveys(self) -> None:
        manager = _FakeManager(
            SurveyMonkeyResumeConfig(next_url=f"{BASE_URL}/surveys/20/pages?per_page=100", remaining_survey_ids=["20"])
        )
        session = _FakeSession([(200, {"data": [{"id": "p2"}], "links": {}})])
        with _patch_session(session):
            batches = list(get_rows("token", BASE_URL, "survey_pages", MagicMock(), manager))  # type: ignore[arg-type]

        # No survey listing happens on resume; it goes straight to the saved child URL.
        assert session.urls == [f"{BASE_URL}/surveys/20/pages?per_page=100"]
        assert batches[0][0] == {"id": "p2", "survey_id": "20"}


class TestGetRowsQuestions:
    def test_extracts_questions_per_survey(self) -> None:
        manager = _FakeManager()
        session = _FakeSession(
            [
                (200, {"data": [{"id": "10"}], "links": {}}),  # survey list
                (200, {"id": "10", "pages": [{"id": "pg1", "questions": [{"id": "q1"}, {"id": "q2"}]}]}),  # details
            ]
        )
        with _patch_session(session):
            batches = list(
                get_rows("token", BASE_URL, "survey_questions", MagicMock(), manager)  # type: ignore[arg-type]
            )

        rows = [row for batch in batches for row in batch]
        assert [r["id"] for r in rows] == ["q1", "q2"]
        assert all(r["survey_id"] == "10" and r["page_id"] == "pg1" for r in rows)
        assert session.urls[-1] == f"{BASE_URL}/surveys/10/details"
