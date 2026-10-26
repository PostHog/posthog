import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lessannoyingcrm import (
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm import (
    LessAnnoyingCRMResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source import (
    LessAnnoyingCRMSource,
)


def _driver() -> SourceDriver:
    return SourceDriver(LessAnnoyingCRMSource(), LessAnnoyingCRMSourceConfig(api_key="secret-key"))


class TestPagination:
    def test_paginates_until_has_more_false_and_progresses_page(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"Results": [{"ContactId": "1"}], "HasMoreResults": True}),
                ScriptedResponse(json={"Results": [{"ContactId": "2"}], "HasMoreResults": False}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"ContactId": "1"}, {"ContactId": "2"}]
        assert [request.json()["Parameters"]["Page"] for request in result.requests] == [1, 2]
        # Checkpoint saved after the first page (more remained), pointing at page 2.
        assert result.saved_states == [LessAnnoyingCRMResumeConfig(page=2)]

    def test_short_page_without_flag_terminates(self) -> None:
        # No HasMoreResults flag and a page shorter than PAGE_SIZE ends pagination via the heuristic.
        result = _driver().run("contacts", [ScriptedResponse(json={"Results": [{"ContactId": "1"}]})])

        assert result.raised is None
        assert result.rows == [{"ContactId": "1"}]
        assert len(result.requests) == 1

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"Results": [{"ContactId": "9"}], "HasMoreResults": False})],
            resume_state=LessAnnoyingCRMResumeConfig(page=4),
        )

        assert result.raised is None
        assert result.requests[0].json()["Parameters"]["Page"] == 4


class TestFanout:
    def test_pipeline_items_walk_every_pipeline_with_all_statuses(self) -> None:
        result = _driver().run(
            "pipeline_items",
            [
                ScriptedResponse(
                    json=[
                        {
                            "PipelineId": "p1",
                            "Statuses": [{"StatusId": "open"}, {"StatusId": "won", "IsActive": False}],
                        },
                        {"PipelineId": "p2", "Statuses": []},
                    ]
                ),
                ScriptedResponse(json={"Results": [{"PipelineItemId": "i1"}], "HasMoreResults": True}),
                ScriptedResponse(json={"Results": [{"PipelineItemId": "i2"}], "HasMoreResults": False}),
                ScriptedResponse(json={"Results": [{"PipelineItemId": "i3"}], "HasMoreResults": False}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"PipelineItemId": "i1"}, {"PipelineItemId": "i2"}, {"PipelineItemId": "i3"}]
        bodies = [request.json() for request in result.requests]
        assert bodies[0]["Function"] == "GetPipelines"
        child_params = [(body["Parameters"]["PipelineId"], body["Parameters"]["Page"]) for body in bodies[1:]]
        assert child_params == [("p1", 1), ("p1", 2), ("p2", 1)]
        # Closed statuses are only returned when named explicitly in StatusFilter.
        assert bodies[1]["Parameters"]["StatusFilter"] == ["open", "won"]
        assert result.saved_states == [
            LessAnnoyingCRMResumeConfig(page=1, parent_id="p1"),
            LessAnnoyingCRMResumeConfig(page=2, parent_id="p1"),
            LessAnnoyingCRMResumeConfig(page=1, parent_id="p2"),
        ]

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
        self, resume: LessAnnoyingCRMResumeConfig, expected: list[tuple[str, int]]
    ) -> None:
        members = {"Results": [{"GroupId": "g", "ContactId": "c"}], "HasMoreResults": False}
        result = _driver().run(
            "group_memberships",
            [
                ScriptedResponse(json={"Results": [{"GroupId": "g1"}, {"GroupId": "g2"}], "HasMoreResults": False}),
                *[ScriptedResponse(json=members) for _ in expected],
            ],
            resume_state=resume,
        )

        assert result.raised is None
        bodies = [request.json() for request in result.requests]
        assert bodies[0]["Function"] == "GetGroups"
        assert [(body["Parameters"]["GroupId"], body["Parameters"]["Page"]) for body in bodies[1:]] == expected


class TestRequestBody:
    def test_tasks_send_required_date_window_and_expand_dict_results(self) -> None:
        # GetTasks nests results as an object keyed by id — every value must become its own row.
        result = _driver().run(
            "tasks",
            [ScriptedResponse(json={"Results": {"a": {"TaskId": "a"}, "b": {"TaskId": "b"}}, "HasMoreResults": False})],
        )

        assert result.raised is None
        assert result.rows == [{"TaskId": "a"}, {"TaskId": "b"}]
        params = result.requests[0].json()["Parameters"]
        assert params["StartDate"] < params["EndDate"]
        assert params["SortDirection"] == "Ascending"
        assert "SortBy" not in params


class TestErrors:
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable(self, status: int) -> None:
        result = _driver().run("contacts", always(ScriptedResponse(status=status, json={"Results": []})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert set(result.paths) == {"/v2/"}

    def test_invalid_credentials_body_raises_matchable_error(self) -> None:
        # LACRM returns a bad key as HTTP 400 with an error envelope. The raised message must contain
        # "Invalid credentials" so the source's non-retryable map disables the sync with friendly copy.
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(
                    status=400, json={"ErrorCode": "x", "ErrorDescription": "Invalid credentials. Please check."}
                )
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "Invalid credentials" in str(result.raised)

    def test_error_envelope_fails_loud(self) -> None:
        # A success-status body carrying an error envelope must raise, not silently sync 0 rows.
        result = _driver().run("contacts", [ScriptedResponse(json={"ErrorCode": "x", "ErrorDescription": "nope"})])

        assert isinstance(result.raised, ValueError)

    def test_sync_redacts_the_api_key(self) -> None:
        result = _driver().run("users", [ScriptedResponse(json=[{"UserId": "1"}])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    def test_invalid_key_status_returns_false(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=400, json={"ErrorCode": "x", "ErrorDescription": "Invalid credentials."})]
        ) as network:
            assert validate_credentials("bad-key") is False

        assert network.requests_log[0].json() == {"Function": "GetUser", "Parameters": {}}

    def test_error_body_on_200_returns_false(self) -> None:
        with scripted_network([ScriptedResponse(json={"ErrorCode": "x", "ErrorDescription": "boom"})]):
            assert validate_credentials("bad-key") is False

    def test_probe_redacts_the_api_key(self) -> None:
        with scripted_network([ScriptedResponse(json={"UserId": "1"})]) as network:
            assert validate_credentials("secret-key") is True

        assert network.session_options[0]["redact_values"] == ("secret-key",)
