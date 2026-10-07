from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    _FORBIDDEN_MESSAGE,
    _INVALID_ORGANIZATION_MESSAGE,
    _INVALID_PAT_MESSAGE,
    _ORGANIZATION_NOT_FOUND_MESSAGE,
    _UNREACHABLE_MESSAGE,
    AZURE_DEVOPS_VERSION_7_2,
    AZURE_DEVOPS_VERSION_LEGACY,
    CLASSIFICATION_NODE_DEPTH,
    TEST_RUN_WINDOW,
    AzureDevOpsAuthError,
    AzureDevOpsResumeConfig,
    _flatten_classification_nodes,
    _format_datetime,
    _validate_organization,
    azure_devops_source,
    get_rows,
    validate_credentials,
    wire_api_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    AZURE_DEVOPS_RELEASE_BASE_URL,
)


def _make_manager(resume_state: AzureDevOpsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], continuation_header: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    resp.headers = {"x-ms-continuationtoken": continuation_header} if continuation_header else {}
    return resp


class TestValidateOrganization:
    @pytest.mark.parametrize("value", ["", "my org", "org?x=1"])
    def test_invalid_organizations_raise(self, value):
        with pytest.raises(ValueError):
            _validate_organization(value)


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_datetime(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, None)),
            # An invalid or expired PAT yields a 203 + HTML sign-in page, not a 401.
            (203, (False, _INVALID_PAT_MESSAGE)),
            (401, (False, _INVALID_PAT_MESSAGE)),
            (403, (False, _FORBIDDEN_MESSAGE)),
            (404, (False, _ORGANIZATION_NOT_FOUND_MESSAGE)),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2) == expected

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_unexpected_status_names_the_status(self, mock_session, status_code):
        # A throttled or Azure-side failure must not be reported as invalid credentials; the message
        # names the status and stays actionable.
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2)

        assert is_valid is False
        assert str(status_code) in (error or "")
        assert "Invalid Azure DevOps credentials" not in (error or "")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_rejects_bad_org_without_request(self, mock_session):
        assert validate_credentials("my org!", "pat", AZURE_DEVOPS_VERSION_7_2) == (
            False,
            _INVALID_ORGANIZATION_MESSAGE,
        )
        mock_session.return_value.get.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_reports_unreachable_on_transport_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, error = validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2)

        assert is_valid is False
        assert error == _UNREACHABLE_MESSAGE
        assert "boom" not in (error or "")


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_builds_fan_out_per_project_with_ascending_order(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response({"value": [{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "builds", mock.MagicMock(), manager, AZURE_DEVOPS_VERSION_7_2))

        assert batches == [[{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]]
        build_url = mock_session.return_value.get.call_args_list[1].args[0]
        parsed = urlparse(build_url)
        assert parsed.path == "/myorg/Alpha/_apis/build/builds"
        assert parse_qs(parsed.query)["queryOrder"] == ["queueTimeAscending"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pull_requests_use_skip_pagination_and_status_all(self, mock_session):
        full_page = {"value": [{"pullRequestId": i} for i in range(200)]}
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response(full_page),
            _response({"value": [{"pullRequestId": 999}]}),
            _response({"value": []}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "pull_requests", mock.MagicMock(), manager, AZURE_DEVOPS_VERSION_7_2))

        assert len(batches) == 2
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list[1:]]
        assert parse_qs(urlparse(urls[0]).query)["searchCriteria.status"] == ["all"]
        assert parse_qs(urlparse(urls[0]).query)["$skip"] == ["0"]
        assert parse_qs(urlparse(urls[1]).query)["$skip"] == ["200"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_revisions_walk_batches_and_flatten(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(
                {
                    "values": [{"id": 1, "rev": 1, "fields": {"System.ChangedDate": "2024-01-01T00:00:00Z"}}],
                    "continuationToken": "tok1",
                    "isLastBatch": False,
                }
            ),
            _response({"values": [{"id": 1, "rev": 2, "fields": {}}], "isLastBatch": True}),
        ]

        manager = _make_manager()
        batches = list(
            get_rows("myorg", "pat", "work_item_revisions", mock.MagicMock(), manager, AZURE_DEVOPS_VERSION_7_2)
        )

        assert batches[0][0]["changed_date"] == "2024-01-01T00:00:00Z"
        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].continuation_token == "tok1"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_revisions_resume_does_not_send_start_date_time(self, mock_session):
        # A continuationToken fully encodes the stream position; pairing it with
        # startDateTime would reset the stream to the watermark on resume.
        mock_session.return_value.get.return_value = _response({"values": [], "isLastBatch": True})

        manager = _make_manager(AzureDevOpsResumeConfig(continuation_token="tok_resume"))
        list(
            get_rows(
                "myorg",
                "pat",
                "work_item_revisions",
                mock.MagicMock(),
                manager,
                AZURE_DEVOPS_VERSION_7_2,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        query = parse_qs(urlparse(mock_session.return_value.get.call_args.args[0]).query)
        assert query["continuationToken"] == ["tok_resume"]
        assert "startDateTime" not in query

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_sign_in_page_raises_auth_error(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 203
        response.ok = True
        mock_session.return_value.get.return_value = response

        manager = _make_manager()
        with pytest.raises(AzureDevOpsAuthError):
            list(get_rows("myorg", "pat", "projects", mock.MagicMock(), manager, AZURE_DEVOPS_VERSION_7_2))


class TestFanOutEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_commits_fan_out_skips_disabled_repositories_and_flattens_the_committer_date(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": "repo-1", "name": "core"}, {"id": "repo-2", "isDisabled": True}]}),
            _response({"value": [{"commitId": "abc", "committer": {"date": "2024-01-02T03:04:05Z"}}]}),
            _response({"value": []}),
        ]

        batches = list(get_rows("myorg", "pat", "commits", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2))

        row = batches[0][0]
        assert row["committer_date"] == "2024-01-02T03:04:05Z"
        assert (row["repository_id"], row["repository_name"], row["project_name"]) == ("repo-1", "core", "Alpha")
        commit_url = mock_session.return_value.get.call_args_list[2].args[0]
        parsed = urlparse(commit_url)
        # The disabled repository must never be requested — commits on it 404.
        assert parsed.path == "/myorg/Alpha/_apis/git/repositories/repo-1/commits"
        assert parse_qs(parsed.query)["searchCriteria.showOldestCommitsFirst"] == ["true"]
        assert len(mock_session.return_value.get.call_args_list) == 4

    THREADS = {
        "value": [
            {
                "id": 141,
                "publishedDate": "2024-01-02T03:04:05Z",
                "comments": [
                    {"id": 1, "content": "looks good"},
                    {"id": 2, "parentCommentId": 1, "content": "thanks"},
                ],
            }
        ]
    }

    def _pull_request_parents(self, child_body: dict[str, Any]) -> list[mock.MagicMock]:
        # The pull request walk is lazy: each PR's child endpoint is requested before
        # the next page of pull requests is asked for.
        return [
            _response(self.PROJECTS),
            _response({"value": [{"pullRequestId": 22, "repository": {"id": "repo-1"}}]}),
            _response(child_body),
            _response({"value": []}),
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pull_request_threads_carry_their_parent_identifiers(self, mock_session):
        mock_session.return_value.get.side_effect = self._pull_request_parents(self.THREADS)

        batches = list(
            get_rows(
                "myorg", "pat", "pull_request_threads", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2
            )
        )

        row = batches[0][0]
        assert (row["id"], row["repository_id"], row["pull_request_id"]) == (141, "repo-1", 22)
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/Alpha/_apis/git/repositories/repo-1/pullRequests/22/threads"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pull_request_thread_comments_flatten_out_of_the_same_response(self, mock_session):
        mock_session.return_value.get.side_effect = self._pull_request_parents(self.THREADS)

        batches = list(
            get_rows(
                "myorg",
                "pat",
                "pull_request_thread_comments",
                mock.MagicMock(),
                _make_manager(),
                AZURE_DEVOPS_VERSION_7_2,
            )
        )

        rows = batches[0]
        assert [row["id"] for row in rows] == [1, 2]
        assert {row["thread_id"] for row in rows} == {141}
        assert {(row["repository_id"], row["pull_request_id"]) for row in rows} == {("repo-1", 22)}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pull_request_reviewers_carry_their_parent_identifiers(self, mock_session):
        mock_session.return_value.get.side_effect = self._pull_request_parents(
            {"value": [{"id": "identity-1", "vote": 10}]}
        )

        batches = list(
            get_rows(
                "myorg", "pat", "pull_request_reviewers", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2
            )
        )

        row = batches[0][0]
        assert (row["id"], row["vote"], row["repository_id"], row["pull_request_id"]) == (
            "identity-1",
            10,
            "repo-1",
            22,
        )
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/Alpha/_apis/git/repositories/repo-1/pullRequests/22/reviewers"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_teams_are_read_by_project_id_not_project_name(self, mock_session):
        # The Core teams route takes a project ID; passing the display name 404s.
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": "team-1", "name": "QA"}]}),
            _response({"value": []}),
        ]

        batches = list(get_rows("myorg", "pat", "teams", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2))

        row = batches[0][0]
        assert (row["id"], row["project_id"], row["project_name"]) == ("team-1", "proj-guid", "Alpha")
        assert urlparse(mock_session.return_value.get.call_args_list[1].args[0]).path == (
            "/myorg/_apis/projects/proj-guid/teams"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_team_members_lift_the_identity_id_to_the_row_root(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": "team-1", "name": "QA"}]}),
            _response({"value": [{"isTeamAdmin": True, "identity": {"id": "identity-1", "displayName": "Ada"}}]}),
            _response({"value": []}),
            _response({"value": []}),
        ]

        batches = list(
            get_rows("myorg", "pat", "team_members", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        row = batches[0][0]
        # identity_id and team_id are the composite primary key, so both must be present.
        assert (row["identity_id"], row["team_id"], row["team_name"]) == ("identity-1", "team-1", "QA")
        assert row["project_id"] == "proj-guid"
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/_apis/projects/proj-guid/teams/team-1/members"
        )


class TestPipelineEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pipelines_paginate_via_header_token_and_carry_the_project(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 3, "name": "deploy"}]}, continuation_header="tok1"),
            _response({"value": [{"id": 4, "name": "release"}]}),
        ]

        batches = list(
            get_rows("myorg", "pat", "pipelines", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        # project_id is half the composite primary key, so it must be present.
        assert [(row["id"], row["project_id"]) for batch in batches for row in batch] == [
            (3, "proj-guid"),
            (4, "proj-guid"),
        ]
        first, second = (call.args[0] for call in mock_session.return_value.get.call_args_list[1:])
        assert urlparse(first).path == "/myorg/proj-guid/_apis/pipelines"
        assert parse_qs(urlparse(second).query)["continuationToken"] == ["tok1"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pipeline_runs_follow_a_continuation_token_without_asking_for_a_page_size(self, mock_session):
        # The listing documents no paging parameters. Reading one response would cap the table
        # at whatever the vendor returns in it, and sending $top could shorten that response.
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 3, "name": "deploy"}]}),
            _response({"value": [{"id": 91}]}, continuation_header="tok1"),
            _response({"value": [{"id": 92}]}),
        ]

        batches = list(
            get_rows("myorg", "pat", "pipeline_runs", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        assert [row["id"] for batch in batches for row in batch] == [91, 92]
        first, second = (
            parse_qs(urlparse(call.args[0]).query) for call in mock_session.return_value.get.call_args_list[2:]
        )
        assert "$top" not in first
        assert second["continuationToken"] == ["tok1"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pipeline_runs_skip_a_pipeline_without_an_id(self, mock_session):
        # Requesting one anyway would build a path with a literal {pipelineId} placeholder.
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"name": "deploy"}]}),
        ]

        batches = list(
            get_rows("myorg", "pat", "pipeline_runs", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        assert batches == []
        assert len(mock_session.return_value.get.call_args_list) == 2


class TestWorkItemLookupEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}
    TYPES = {"value": [{"name": "User Story", "referenceName": "Microsoft.VSTS.WorkItemTypes.UserStory"}]}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_types_carry_the_project_reference(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(self.PROJECTS), _response(self.TYPES)]

        batches = list(
            get_rows("myorg", "pat", "work_item_types", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        row = batches[0][0]
        # project_id is half the composite primary key, so it must be present.
        assert (row["referenceName"], row["project_id"], row["project_name"]) == (
            "Microsoft.VSTS.WorkItemTypes.UserStory",
            "proj-guid",
            "Alpha",
        )
        assert urlparse(mock_session.return_value.get.call_args_list[1].args[0]).path == (
            "/myorg/proj-guid/_apis/wit/workitemtypes"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_type_states_fan_out_over_types_and_encode_the_type_name(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response(self.TYPES),
            _response({"value": [{"name": "Active", "color": "007acc", "category": "InProgress"}]}),
        ]

        batches = list(
            get_rows(
                "myorg", "pat", "work_item_type_states", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2
            )
        )

        row = batches[0][0]
        # A state row carries only name/colour/category, so the rest of the primary key
        # has to be injected from the parent type.
        assert (row["name"], row["category"], row["project_id"], row["work_item_type"]) == (
            "Active",
            "InProgress",
            "proj-guid",
            "User Story",
        )
        assert row["work_item_type_reference_name"] == "Microsoft.VSTS.WorkItemTypes.UserStory"
        # Type names contain spaces, which must be percent-encoded into the path.
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/proj-guid/_apis/wit/workitemtypes/User%20Story/states"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_classification_nodes_request_the_full_tree_depth(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(self.PROJECTS), _response({"value": []})]

        list(
            get_rows(
                "myorg",
                "pat",
                "work_item_classification_nodes",
                mock.MagicMock(),
                _make_manager(),
                AZURE_DEVOPS_VERSION_7_2,
            )
        )

        parsed = urlparse(mock_session.return_value.get.call_args_list[1].args[0])
        assert parsed.path == "/myorg/proj-guid/_apis/wit/classificationnodes"
        # Without $depth the API answers with the two roots and no children at all.
        assert parse_qs(parsed.query)["$depth"] == [str(CLASSIFICATION_NODE_DEPTH)]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_iterations_fan_out_over_teams(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": "team-1", "name": "QA"}]}),
            _response({"value": [{"id": "iter-guid", "name": "Sprint 1", "path": "Alpha\\Sprint 1"}]}),
            _response({"value": []}),
        ]

        batches = list(
            get_rows("myorg", "pat", "work_iterations", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        row = batches[0][0]
        # team_id is half the composite primary key: teams share one project iteration tree,
        # so the same iteration id comes back for every team subscribed to it.
        assert (row["id"], row["team_id"], row["team_name"], row["project_id"]) == (
            "iter-guid",
            "team-1",
            "QA",
            "proj-guid",
        )
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/proj-guid/team-1/_apis/work/teamsettings/iterations"
        )


class TestFlattenClassificationNodes:
    PROJECT = {"id": "proj-guid", "name": "Alpha"}

    def test_warns_when_the_tree_is_cut_off_at_the_requested_depth(self):
        logger = mock.MagicMock()

        _flatten_classification_nodes({"id": 1, "hasChildren": True}, self.PROJECT, logger)

        logger.warning.assert_called_once()


class TestBuildEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_build_definitions_carry_the_project_reference(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 7, "name": "core-ci", "createdDate": "2024-01-02T03:04:05Z"}]}),
        ]

        batches = list(
            get_rows("myorg", "pat", "build_definitions", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2)
        )

        row = batches[0][0]
        # project_id is half the composite primary key, so it must be present.
        assert (row["id"], row["project_id"], row["project_name"]) == (7, "proj-guid", "Alpha")
        parsed = urlparse(mock_session.return_value.get.call_args_list[1].args[0])
        assert parsed.path == "/myorg/Alpha/_apis/build/definitions"
        assert parse_qs(parsed.query)["queryOrder"] == ["lastModifiedAscending"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_build_timeline_records_carry_the_build_they_describe(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response(
                {"value": [{"id": 41, "queueTime": "2024-01-02T03:04:05Z", "finishTime": "2024-01-02T03:20:00Z"}]}
            ),
            _response({"id": "timeline-1", "records": [{"id": "rec-1", "type": "Job", "result": "failed"}]}),
        ]

        batches = list(
            get_rows(
                "myorg", "pat", "build_timeline_records", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2
            )
        )

        row = batches[0][0]
        # build_id is half the composite primary key; the queue time partitions and the
        # finish time is the watermark, and only the parent build carries either.
        assert (row["id"], row["build_id"], row["timeline_id"]) == ("rec-1", 41, "timeline-1")
        assert row["build_queue_time"] == "2024-01-02T03:04:05Z"
        assert row["build_finish_time"] == "2024-01-02T03:20:00Z"
        assert row["project_name"] == "Alpha"
        assert urlparse(mock_session.return_value.get.call_args_list[2].args[0]).path == (
            "/myorg/Alpha/_apis/build/builds/41/timeline"
        )


class TestReleaseEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("releases", "/myorg/Alpha/_apis/release/releases"),
            ("release_deployments", "/myorg/Alpha/_apis/release/deployments"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_release_endpoints_are_read_from_the_release_host(self, mock_session, endpoint, path):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 5, "name": "Release-5"}]}),
        ]

        batches = list(
            get_rows(
                "myorg",
                "pat",
                endpoint,
                mock.MagicMock(),
                _make_manager(),
                AZURE_DEVOPS_VERSION_7_2,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        row = batches[0][0]
        assert (row["id"], row["project_id"], row["project_name"]) == (5, "proj-guid", "Alpha")
        # Release Management is served from its own host; dev.azure.com 404s these routes.
        projects_url, release_url = (call.args[0] for call in mock_session.return_value.get.call_args_list)
        assert projects_url.startswith("https://dev.azure.com/")
        assert release_url.startswith(f"{AZURE_DEVOPS_RELEASE_BASE_URL}/")
        parsed = urlparse(release_url)
        assert parsed.path == path
        assert parse_qs(parsed.query)["queryOrder"] == ["ascending"]


class TestTestRunEndpoint:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_full_refresh_walks_the_unfiltered_listing(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 3, "totalTests": 10, "passedTests": 9}]}),
            _response({"value": []}),
        ]

        batches = list(
            get_rows(
                "myorg",
                "pat",
                "test_runs",
                mock.MagicMock(),
                _make_manager(),
                AZURE_DEVOPS_VERSION_7_2,
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert batches[0][0]["project_id"] == "proj-guid"
        query = parse_qs(urlparse(mock_session.return_value.get.call_args_list[1].args[0]).query)
        assert query["$skip"] == ["0"]
        assert "minLastUpdatedDate" not in query

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_incremental_sends_both_window_bounds(self, mock_session):
        # Both bounds are mandatory on the filtered query and the span may not exceed
        # the cap, so sending minLastUpdatedDate alone is rejected.
        since = datetime.now(UTC) - timedelta(days=2)
        mock_session.return_value.get.side_effect = [
            _response(self.PROJECTS),
            _response({"value": [{"id": 3}]}),
        ]

        list(
            get_rows(
                "myorg",
                "pat",
                "test_runs",
                mock.MagicMock(),
                _make_manager(),
                AZURE_DEVOPS_VERSION_7_2,
                should_use_incremental_field=True,
                db_incremental_field_last_value=since,
            )
        )

        query = parse_qs(urlparse(mock_session.return_value.get.call_args_list[1].args[0]).query)
        assert query["minLastUpdatedDate"] == [_format_datetime(since)]
        window_start = datetime.fromisoformat(query["minLastUpdatedDate"][0].replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(query["maxLastUpdatedDate"][0].replace("Z", "+00:00"))
        assert window_end - window_start <= TEST_RUN_WINDOW
        assert "$skip" not in query


class TestAzureDevOpsSourceResponse:
    def test_pull_requests_are_desc_sorted(self):
        response = azure_devops_source(
            "myorg", "pat", "pull_requests", mock.MagicMock(), _make_manager(), AZURE_DEVOPS_VERSION_7_2
        )
        assert response.sort_mode == "desc"


class TestApiVersionDispatch:
    def test_wire_api_version_rejects_unknown_label(self):
        # A silent fallthrough would send no api-version and track whatever the vendor defaults to.
        with pytest.raises(ValueError):
            wire_api_version("nope")

    @pytest.mark.parametrize("version, wire", [(AZURE_DEVOPS_VERSION_LEGACY, "7.1"), (AZURE_DEVOPS_VERSION_7_2, "7.2")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_get_rows_sends_pinned_api_version_on_the_wire(self, mock_session, version, wire):
        mock_session.return_value.get.return_value = _response({"value": []})

        list(get_rows("myorg", "pat", "projects", mock.MagicMock(), _make_manager(), version))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["api-version"] == [wire]
