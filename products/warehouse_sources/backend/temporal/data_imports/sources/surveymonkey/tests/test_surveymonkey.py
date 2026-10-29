from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveymonkey import (
    SurveyMonkeySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source import SurveyMonkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey import (
    SurveyMonkeyResumeConfig,
    _format_incremental_value,
    validate_credentials,
)

BASE_URL = "https://api.surveymonkey.com/v3"


def _page(
    items: list[dict[str, Any]] | None, *, next_url: str | None = None, status_code: int = 200
) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or [], "links": {}}
    if next_url is not None:
        body["links"]["next"] = next_url
    return ScriptedResponse(status=status_code, json=body)


def _raw(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SurveyMonkeySource(), SurveyMonkeySourceConfig(access_token="token", data_center="us"))


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


class TestSurveysTopLevel:
    def test_paginates_via_links_next(self) -> None:
        result = _driver().run(
            "surveys",
            [
                _page([{"id": "1"}], next_url=f"{BASE_URL}/surveys?page=2"),
                _page([{"id": "2"}]),
            ],
        )

        assert [r["id"] for r in result.rows] == ["1", "2"]
        # Page 1 carries the static list params; the next-page link is self-contained (params cleared).
        first = result.requests[0]
        assert first.path == "/v3/surveys"
        assert first.param("per_page") == "100"
        assert "date_created" in (first.param("include") or "")
        assert first.param("sort_by") == "date_modified"
        assert first.param("sort_order") == "ASC"
        assert result.urls[1] == f"{BASE_URL}/surveys?page=2"
        # Checkpoint once, pointing at the next page URL; the last page (no next) saves nothing.
        assert [s.paginator_state for s in result.saved_states] == [{"next_url": f"{BASE_URL}/surveys?page=2"}]

    def test_applies_modified_cutoff_when_incremental(self) -> None:
        result = _driver().run(
            "surveys",
            [_page([{"id": "1"}])],
            incremental_field="date_modified",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("start_modified_at") == "2026-01-01T00:00:00"


class TestFanOut:
    def test_fans_out_over_surveys_and_injects_survey_id(self) -> None:
        result = _driver().run(
            "survey_pages",
            [
                _page([{"id": "10"}, {"id": "20"}]),  # /surveys list (one page)
                _page([{"id": "p1"}]),  # survey 10 pages
                _page([{"id": "p2"}]),  # survey 20 pages
            ],
        )

        assert result.rows == [{"id": "p1", "survey_id": "10"}, {"id": "p2", "survey_id": "20"}]
        child_paths = [path for path in result.paths if "/pages" in path]
        assert child_paths == ["/v3/surveys/10/pages", "/v3/surveys/20/pages"]
        # The survey enumeration is bare — no include/sort leaks into the parent listing.
        assert result.requests[0].path == "/v3/surveys"
        assert result.requests[0].param("include") is None
        assert result.requests[0].param("sort_by") is None

    def test_responses_apply_created_cutoff_and_no_sort(self) -> None:
        result = _driver().run(
            "survey_responses",
            [
                _page([{"id": "10"}]),  # /surveys list
                _page([{"id": "r1"}]),  # survey 10 responses
            ],
            incremental_field="date_created",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.rows == [{"id": "r1", "survey_id": "10"}]
        child = next(request for request in result.requests if "/responses/bulk" in request.path)
        assert child.path == "/v3/surveys/10/responses/bulk"
        assert child.param("start_created_at") == "2026-01-01T00:00:00"
        # responses/bulk has no server-side sort enum, so we don't send sort_by.
        assert child.param("sort_by") is None


class TestQuestions:
    def test_explodes_questions_per_survey(self) -> None:
        result = _driver().run(
            "survey_questions",
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

        rows = result.rows
        assert [r["id"] for r in rows] == ["q1", "q2", "q3"]
        assert all(r["survey_id"] == "10" for r in rows)
        assert [r["page_id"] for r in rows] == ["pg1", "pg1", "pg2"]
        assert result.paths[-1] == "/v3/surveys/10/details"


class TestRetry:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_exhaust_then_raise(self, status_code) -> None:
        result = _driver().run("surveys", always(_page([], status_code=status_code)))

        assert result.raised is not None
        # 5 attempts total (the client default) before reraise.
        assert len(result.requests) == 5

    def test_client_error_is_not_retried(self) -> None:
        result = _driver().run("surveys", [_page([], status_code=401)])

        assert isinstance(result.raised, requests.HTTPError)
        # A 401 is permanent — issued exactly once, no retry.
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code, expected_ok) -> None:
        body = {} if status_code == 200 else {"error": {"message": "nope"}}
        with scripted_network(always(_raw(body, status_code=status_code))) as network:
            ok, error = validate_credentials("token", BASE_URL)

        assert ok is expected_ok
        if not ok:
            assert error
        assert network.requests_log[0].url == f"{BASE_URL}/users/me"

    def test_token_is_declared_redactable(self) -> None:
        with scripted_network([_raw({})]) as network:
            validate_credentials("secret-token", BASE_URL)

        # The token must reach the tracked session's redaction set so it's scrubbed from errors/logs.
        assert network.session_options[0].get("redact_values") == ("secret-token",)


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
