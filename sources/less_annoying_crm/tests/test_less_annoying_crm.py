import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from sources.less_annoying_crm.less_annoying_crm import (
    LessAnnoyingCRMResumeConfig,
    less_annoying_crm_source,
    validate_credentials,
)
from sources.sdk import RESTClientRetryableError

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the less_annoying_crm module.
LACRM_SESSION_PATCH = "sources.less_annoying_crm.less_annoying_crm.make_tracked_session"
# tenacity sleeps between client retries; patch its clock so the retry test stays fast.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LessAnnoyingCRMResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages (the paginator writes ``Page`` into
    its nested ``Parameters``), so inspecting it after the run shows only the final state — snapshot a
    deep copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(json.loads(json.dumps(request.json or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return less_annoying_crm_source("secret-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_has_more_false_and_progresses_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response({"Results": [{"ContactId": "1"}], "HasMoreResults": True}),
                _response({"Results": [{"ContactId": "2"}], "HasMoreResults": False}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == [{"ContactId": "1"}, {"ContactId": "2"}]
        assert bodies[0]["Parameters"]["Page"] == 1
        assert bodies[1]["Parameters"]["Page"] == 2
        # Checkpoint saved after the first page (more remained), pointing at page 2.
        manager.save_state.assert_called_once_with(LessAnnoyingCRMResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_without_flag_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        # No HasMoreResults flag and a page shorter than PAGE_SIZE ends pagination via the heuristic.
        _wire(session, [_response({"Results": [{"ContactId": "1"}]})])

        rows = _rows(_source("contacts", _make_manager()))

        assert rows == [{"ContactId": "1"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response({"Results": [{"ContactId": "9"}], "HasMoreResults": False})])

        _rows(_source("contacts", _make_manager(LessAnnoyingCRMResumeConfig(page=4))))

        assert bodies[0]["Parameters"]["Page"] == 4


class TestFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pipeline_items_walk_every_pipeline_with_all_statuses(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response(
                    [
                        {
                            "PipelineId": "p1",
                            "Statuses": [{"StatusId": "open"}, {"StatusId": "won", "IsActive": False}],
                        },
                        {"PipelineId": "p2", "Statuses": []},
                    ]
                ),
                _response({"Results": [{"PipelineItemId": "i1"}], "HasMoreResults": True}),
                _response({"Results": [{"PipelineItemId": "i2"}], "HasMoreResults": False}),
                _response({"Results": [{"PipelineItemId": "i3"}], "HasMoreResults": False}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("pipeline_items", manager))

        assert rows == [{"PipelineItemId": "i1"}, {"PipelineItemId": "i2"}, {"PipelineItemId": "i3"}]
        assert bodies[0]["Function"] == "GetPipelines"
        child_params = [(b["Parameters"]["PipelineId"], b["Parameters"]["Page"]) for b in bodies[1:]]
        assert child_params == [("p1", 1), ("p1", 2), ("p2", 1)]
        # Closed statuses are only returned when named explicitly in StatusFilter.
        assert bodies[1]["Parameters"]["StatusFilter"] == ["open", "won"]
        assert manager.save_state.call_args_list == [
            mock.call(LessAnnoyingCRMResumeConfig(page=1, parent_id="p1")),
            mock.call(LessAnnoyingCRMResumeConfig(page=2, parent_id="p1")),
            mock.call(LessAnnoyingCRMResumeConfig(page=1, parent_id="p2")),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize(
        "resume,expected",
        [
            # Resumes inside the saved group at the saved page, skipping groups already synced.
            (LessAnnoyingCRMResumeConfig(page=3, parent_id="g2"), [("g2", 3)]),
            # A group deleted since the checkpoint restarts the fan-out from the first group.
            (LessAnnoyingCRMResumeConfig(page=3, parent_id="gone"), [("g1", 1), ("g2", 1)]),
        ],
    )
    def test_group_memberships_resume(
        self, MockSession, resume: LessAnnoyingCRMResumeConfig, expected: list[tuple[str, int]]
    ) -> None:
        session = MockSession.return_value
        members = {"Results": [{"GroupId": "g", "ContactId": "c"}], "HasMoreResults": False}
        bodies = _wire(
            session,
            [
                _response({"Results": [{"GroupId": "g1"}, {"GroupId": "g2"}], "HasMoreResults": False}),
                _response(members),
                _response(members),
            ],
        )

        _rows(_source("group_memberships", _make_manager(resume)))

        assert bodies[0]["Function"] == "GetGroups"
        assert [(b["Parameters"]["GroupId"], b["Parameters"]["Page"]) for b in bodies[1:]] == expected


class TestRequestBody:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tasks_send_required_date_window_and_expand_dict_results(self, MockSession) -> None:
        session = MockSession.return_value
        # GetTasks nests results as an object keyed by id — every value must become its own row.
        bodies = _wire(
            session,
            [_response({"Results": {"a": {"TaskId": "a"}, "b": {"TaskId": "b"}}, "HasMoreResults": False})],
        )

        rows = _rows(_source("tasks", _make_manager()))

        assert rows == [{"TaskId": "a"}, {"TaskId": "b"}]
        params = bodies[0]["Parameters"]
        assert params["StartDate"] < params["EndDate"]
        assert params["SortDirection"] == "Ascending"
        assert "SortBy" not in params


class TestErrors:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable(self, MockSession, _sleep, status: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Results": []}, status_code=status) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_invalid_credentials_body_raises_matchable_error(self, MockSession) -> None:
        session = MockSession.return_value
        # LACRM returns a bad key as HTTP 400 with an error envelope. The raised message must contain
        # "Invalid credentials" so the source's non-retryable map disables the sync with friendly copy.
        _wire(
            session,
            [_response({"ErrorCode": "x", "ErrorDescription": "Invalid credentials. Please check."}, status_code=400)],
        )

        with pytest.raises(ValueError, match="Invalid credentials"):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_envelope_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        # A success-status body carrying an error envelope must raise, not silently sync 0 rows.
        _wire(session, [_response({"ErrorCode": "x", "ErrorDescription": "nope"})])

        with pytest.raises(ValueError):
            _rows(_source("contacts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_redacts_the_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"UserId": "1"}])])

        _rows(_source("users", _make_manager()))

        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @mock.patch(LACRM_SESSION_PATCH)
    def test_invalid_key_status_returns_false(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response(
            {"ErrorCode": "x", "ErrorDescription": "Invalid credentials."}, status_code=400
        )
        assert validate_credentials("bad-key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_error_body_on_200_returns_false(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response({"ErrorCode": "x", "ErrorDescription": "boom"})
        assert validate_credentials("bad-key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(LACRM_SESSION_PATCH)
    def test_probe_redacts_the_api_key(self, mock_session) -> None:
        mock_session.return_value.post.return_value = _response({"UserId": "1"})
        validate_credentials("secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)
