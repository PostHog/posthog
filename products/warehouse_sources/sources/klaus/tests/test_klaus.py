from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klaus import KlausSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus import (
    DEFAULT_FROM_DATE,
    KlausResumeConfig,
    _build_params,
    _format_datetime,
    get_base_url,
    get_rows,
    klaus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import KLAUS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source import KlausSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus"


def _response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.is_redirect = status in (301, 302, 303, 307, 308)
    response.json.return_value = body
    response.headers = headers or {}
    response.text = str(body)
    return response


def _manager(resume: KlausResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    endpoint: str,
    responses: list[MagicMock],
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], MagicMock, MagicMock]:
    manager = manager if manager is not None else _manager()
    with patch(f"{MODULE}.make_tracked_session") as MockSession:
        session = MockSession.return_value
        session.get.side_effect = responses
        batches = list(
            get_rows(
                subdomain="acme",
                api_token="test-token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches, session, manager


def _driver() -> SourceDriver:
    return SourceDriver(KlausSource(), KlausSourceConfig(subdomain="acme", api_token="test-token"))


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("acme", "https://acme.zendesk.com/qa"),
            ("  ACME  ", "https://acme.zendesk.com/qa"),
            ("acme.zendesk.com", "https://acme.zendesk.com/qa"),
            ("https://acme.zendesk.com/", "https://acme.zendesk.com/qa"),
            ("my-team2", "https://my-team2.zendesk.com/qa"),
        ],
    )
    def test_normalizes_valid_input(self, raw: str, expected: str) -> None:
        assert get_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "evil.com/acme",
            "acme.evil.com",
            "acme zendesk",
            "-acme",
            "acme?x=1",
        ],
    )
    def test_rejects_host_escapes(self, raw: str) -> None:
        # A subdomain with dots, slashes, or other URL syntax could splice a
        # different host into the request URL and receive the bearer token.
        with pytest.raises(ValueError):
            get_base_url(raw)


class TestBuildParams:
    @pytest.mark.parametrize(
        "last_value",
        [
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            "2026-01-02T12:00:00Z",
            "2026-01-02T12:00:00+00:00",
        ],
    )
    def test_incremental_value_applies_overlap(self, last_value: Any) -> None:
        # The watermark is pulled back by the overlap window so an undocumented
        # exclusive fromDate boundary can't skip same-timestamp rows.
        params = _build_params(KLAUS_ENDPOINTS["reviews"], True, last_value)
        assert params == {"fromDate": "2026-01-02T11:00:00Z"}


class TestPagination:
    def _page(self, items: list[dict[str, Any]], page: int | None, page_size: int, total: int | None = None) -> dict:
        pagination: dict[str, Any] = {"pageSize": page_size}
        if page is not None:
            pagination["page"] = page
        if total is not None:
            pagination["total"] = total
        return {"conversations": items, "pagination": pagination}

    def test_stuck_page_echo_raises_instead_of_looping(self) -> None:
        stuck = self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)
        result = _driver().run("reviews", [ScriptedResponse(json=stuck), ScriptedResponse(json=stuck)])

        assert isinstance(result.raised, Exception)
        assert "did not advance" in str(result.raised)

    def test_incremental_from_date_sent_on_every_page(self) -> None:
        responses = [
            ScriptedResponse(json=self._page([{"externalId": "a"}, {"externalId": "b"}], page=1, page_size=2)),
            ScriptedResponse(json=self._page([], page=2, page_size=2)),
        ]
        result = _driver().run(
            "reviews",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("fromDate") == ["2026-01-02T11:00:00Z"] * 2


class TestFanOut:
    def test_fans_out_over_workspaces_and_injects_workspace_id(self) -> None:
        responses = [
            ScriptedResponse(json={"workspaces": [{"id": 1, "name": "Support"}, {"id": 2, "name": "Sales"}]}),
            ScriptedResponse(json={"data": [{"id": "10"}]}),
            ScriptedResponse(json={"data": [{"id": "10"}]}),
        ]
        result = _driver().run("scorecards", responses)

        assert result.raised is None
        assert result.urls == [
            "https://acme.zendesk.com/qa/api/export/workspaces",
            "https://acme.zendesk.com/qa/api/export/workspace/1/scorecards",
            "https://acme.zendesk.com/qa/api/export/workspace/2/scorecards",
        ]
        # The injected workspace id keeps the composite primary key unique table-wide
        # when the same scorecard id exists in more than one workspace.
        assert result.items == [[{"id": "10", "workspace_id": "1"}], [{"id": "10", "workspace_id": "2"}]]
        assert result.saved_states == [KlausResumeConfig(next_page=None, workspace_id="2")]

    def test_resume_skips_completed_workspaces(self) -> None:
        responses = [
            ScriptedResponse(json={"workspaces": [{"id": 1}, {"id": 2}]}),
            ScriptedResponse(json={"data": [{"id": "10"}]}),
        ]
        result = _driver().run(
            "scorecards", responses, resume_state=KlausResumeConfig(next_page=None, workspace_id="2")
        )

        assert result.raised is None
        assert result.urls == [
            "https://acme.zendesk.com/qa/api/export/workspaces",
            "https://acme.zendesk.com/qa/api/export/workspace/2/scorecards",
        ]
        assert result.items == [[{"id": "10", "workspace_id": "2"}]]

    def test_fans_out_over_quizzes_and_injects_quiz_id(self) -> None:
        responses = [
            ScriptedResponse(json={"quizzes": [{"id": "7", "name": "Refunds"}, {"id": "8", "name": "Tone"}]}),
            ScriptedResponse(
                json={"responses": [{"responseId": "100", "userId": "1", "correctAnswerPercentage": "80"}]}
            ),
            ScriptedResponse(json={}),
        ]
        result = _driver().run("quiz_responses", responses)

        assert result.raised is None
        assert result.urls == [
            "https://acme.zendesk.com/qa/api/export/quizzes",
            "https://acme.zendesk.com/qa/api/export/quizzes/7/responses",
            "https://acme.zendesk.com/qa/api/export/quizzes/8/responses",
        ]
        # proto3 JSON drops an empty repeated field, so a quiz with no responses
        # returns `{}` and must yield nothing.
        assert result.items == [[{"responseId": "100", "userId": "1", "correctAnswerPercentage": "80", "quiz_id": "7"}]]

    def test_single_object_response_becomes_one_row_per_quiz(self) -> None:
        responses = [
            ScriptedResponse(json={"quizzes": [{"id": "7"}]}),
            ScriptedResponse(json={"id": "7", "name": "Refunds", "responseCount": "3", "fields": [{"id": "1"}]}),
        ]
        result = _driver().run("quiz_overviews", responses)

        assert result.raised is None
        assert result.urls[1] == "https://acme.zendesk.com/qa/api/export/quizzes/7/overview"
        assert result.items == [
            [{"id": "7", "name": "Refunds", "responseCount": "3", "fields": [{"id": "1"}], "quiz_id": "7"}]
        ]

    def test_from_date_applies_to_workspace_requests_but_not_workspace_listing(self) -> None:
        responses = [
            ScriptedResponse(json={"workspaces": [{"id": 1}]}),
            ScriptedResponse(json={"calibrationSessions": [{"id": "s1"}], "pagination": {"page": 1, "pageSize": 100}}),
        ]
        result = _driver().run("calibration_sessions", responses)

        assert result.raised is None
        assert result.params("fromDate") == [None, _format_datetime(DEFAULT_FROM_DATE)]


class TestRetry:
    def test_429_is_retried_honoring_retry_after(self) -> None:
        responses = [
            _response({}, status=429, headers={"Retry-After": "30"}),
            _response({"users": [{"id": "1"}]}),
        ]
        with patch("time.sleep") as mock_sleep:
            batches, _, _ = _drive("users", responses)

        assert batches == [[{"id": "1"}]]
        assert mock_sleep.call_args.args[0] == 31.0


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            # A throttled probe still reached the account's API; the aggressive public
            # rate limit must not block source creation.
            (429, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            valid, error = validate_credentials("acme", "test-token")

        assert {request.path for request in network.requests_log} == {"/qa/api/export/users"}
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_invalid_subdomain_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials("acme.evil.com", "test-token")

        assert valid is False
        assert error is not None
        assert network.requests_log == []
        assert network.session_options == []

    def test_network_error_returns_message(self) -> None:
        with scripted_network([Exception("boom")]):
            valid, error = validate_credentials("acme", "test-token")

        assert valid is False
        assert error == "boom"


class TestGetRowsIsLazy:
    def test_no_request_until_iterated(self) -> None:
        # source_for_pipeline builds the SourceResponse eagerly; the first HTTP call
        # must not happen until the pipeline starts consuming items.
        with patch(f"{MODULE}.make_tracked_session") as MockSession:
            response = klaus_source("acme", "token", "users", MagicMock(), _manager())
            MockSession.assert_not_called()

            MockSession.return_value.get.return_value = _response({"users": [{"id": "1"}]})
            items = response.items()
            assert isinstance(items, Iterator)
            assert list(items) == [[{"id": "1"}]]
