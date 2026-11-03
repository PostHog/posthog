from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
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
    validate_credentials,
    wire_api_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    AZURE_DEVOPS_RELEASE_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source import AzureDevOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azuredevops import (
    AzureDevOpsSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AzureDevOpsSource(), AzureDevOpsSourceConfig(organization="myorg", personal_access_token="pat"))


def _response(body: dict[str, Any], continuation_header: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json=body,
        headers={"x-ms-continuationtoken": continuation_header} if continuation_header else {},
    )


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
            # An invalid or expired PAT yields a 203 + HTML sign-in page, not a 401.
            (203, (False, _INVALID_PAT_MESSAGE)),
            (404, (False, _ORGANIZATION_NOT_FOUND_MESSAGE)),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2) == expected

        assert network.requests_log[0].path == "/myorg/_apis/projects"
        assert network.requests_log[0].param("$top") == "1"
        assert network.requests_log[0].param("api-version") == "7.2"

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_validate_credentials_unexpected_status_names_the_status(self, status_code):
        # A throttled or Azure-side failure must not be reported as invalid credentials; the message
        # names the status and stays actionable.
        with scripted_network(always(ScriptedResponse(status=status_code))):
            is_valid, error = validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2)

        assert is_valid is False
        assert str(status_code) in (error or "")
        assert "Invalid Azure DevOps credentials" not in (error or "")

    def test_validate_credentials_rejects_bad_org_without_request(self):
        with scripted_network([]) as network:
            assert validate_credentials("my org!", "pat", AZURE_DEVOPS_VERSION_7_2) == (
                False,
                _INVALID_ORGANIZATION_MESSAGE,
            )
        assert network.requests_log == []

    def test_validate_credentials_reports_unreachable_on_transport_error(self):
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            is_valid, error = validate_credentials("myorg", "pat", AZURE_DEVOPS_VERSION_7_2)

        assert network.requests_log[0].path == "/myorg/_apis/projects"
        assert is_valid is False
        assert error == _UNREACHABLE_MESSAGE
        assert "boom" not in (error or "")


class TestGetRows:
    def test_builds_fan_out_per_project_with_ascending_order(self):
        result = _driver().run(
            "builds",
            [
                _response({"value": [{"id": "p1", "name": "Alpha"}]}),
                _response({"value": [{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]]
        assert result.paths[1] == "/myorg/Alpha/_apis/build/builds"
        assert result.requests[1].param("queryOrder") == "queueTimeAscending"

    def test_pull_requests_use_skip_pagination_and_status_all(self):
        full_page = {"value": [{"pullRequestId": i} for i in range(200)]}
        result = _driver().run(
            "pull_requests",
            [
                _response({"value": [{"id": "p1", "name": "Alpha"}]}),
                _response(full_page),
                _response({"value": [{"pullRequestId": 999}]}),
                _response({"value": []}),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.requests[1].param("searchCriteria.status") == "all"
        assert result.params("$skip")[1:] == ["0", "200", "201"]

    def test_work_item_revisions_walk_batches_and_flatten(self):
        result = _driver().run(
            "work_item_revisions",
            [
                _response(
                    {
                        "values": [{"id": 1, "rev": 1, "fields": {"System.ChangedDate": "2024-01-01T00:00:00Z"}}],
                        "continuationToken": "tok1",
                        "isLastBatch": False,
                    }
                ),
                _response({"values": [{"id": 1, "rev": 2, "fields": {}}], "isLastBatch": True}),
            ],
        )

        assert result.raised is None
        assert result.items[0][0]["changed_date"] == "2024-01-01T00:00:00Z"
        assert len(result.items) == 2
        assert result.saved_states == [AzureDevOpsResumeConfig(continuation_token="tok1")]

    def test_work_item_revisions_resume_does_not_send_start_date_time(self):
        # A continuationToken fully encodes the stream position; pairing it with
        # startDateTime would reset the stream to the watermark on resume.
        result = _driver().run(
            "work_item_revisions",
            [_response({"values": [], "isLastBatch": True})],
            resume_state=AzureDevOpsResumeConfig(continuation_token="tok_resume"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("continuationToken") == "tok_resume"
        assert result.requests[0].param("startDateTime") is None

    def test_sign_in_page_raises_auth_error(self):
        result = _driver().run("projects", [ScriptedResponse(status=203)])

        assert isinstance(result.raised, AzureDevOpsAuthError)


class TestFanOutEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    def test_commits_fan_out_skips_disabled_repositories_and_flattens_the_committer_date(self):
        result = _driver().run(
            "commits",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": "repo-1", "name": "core"}, {"id": "repo-2", "isDisabled": True}]}),
                _response({"value": [{"commitId": "abc", "committer": {"date": "2024-01-02T03:04:05Z"}}]}),
                _response({"value": []}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        assert row["committer_date"] == "2024-01-02T03:04:05Z"
        assert (row["repository_id"], row["repository_name"], row["project_name"]) == ("repo-1", "core", "Alpha")
        # The disabled repository must never be requested — commits on it 404.
        assert result.paths[2] == "/myorg/Alpha/_apis/git/repositories/repo-1/commits"
        assert result.requests[2].param("searchCriteria.showOldestCommitsFirst") == "true"
        assert len(result.requests) == 4

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

    def _pull_request_parents(self, child_body: dict[str, Any]) -> list[ScriptedResponse]:
        # The pull request walk is lazy: each PR's child endpoint is requested before
        # the next page of pull requests is asked for.
        return [
            _response(self.PROJECTS),
            _response({"value": [{"pullRequestId": 22, "repository": {"id": "repo-1"}}]}),
            _response(child_body),
            _response({"value": []}),
        ]

    def test_pull_request_threads_carry_their_parent_identifiers(self):
        result = _driver().run("pull_request_threads", self._pull_request_parents(self.THREADS))

        assert result.raised is None
        row = result.rows[0]
        assert (row["id"], row["repository_id"], row["pull_request_id"]) == (141, "repo-1", 22)
        assert result.paths[2] == "/myorg/Alpha/_apis/git/repositories/repo-1/pullRequests/22/threads"

    def test_pull_request_thread_comments_flatten_out_of_the_same_response(self):
        result = _driver().run("pull_request_thread_comments", self._pull_request_parents(self.THREADS))

        assert result.raised is None
        rows = result.items[0]
        assert [row["id"] for row in rows] == [1, 2]
        assert {row["thread_id"] for row in rows} == {141}
        assert {(row["repository_id"], row["pull_request_id"]) for row in rows} == {("repo-1", 22)}

    def test_pull_request_reviewers_carry_their_parent_identifiers(self):
        result = _driver().run(
            "pull_request_reviewers",
            self._pull_request_parents({"value": [{"id": "identity-1", "vote": 10}]}),
        )

        assert result.raised is None
        row = result.rows[0]
        assert (row["id"], row["vote"], row["repository_id"], row["pull_request_id"]) == (
            "identity-1",
            10,
            "repo-1",
            22,
        )
        assert result.paths[2] == "/myorg/Alpha/_apis/git/repositories/repo-1/pullRequests/22/reviewers"

    def test_teams_are_read_by_project_id_not_project_name(self):
        # The Core teams route takes a project ID; passing the display name 404s.
        result = _driver().run(
            "teams",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": "team-1", "name": "QA"}]}),
                _response({"value": []}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        assert (row["id"], row["project_id"], row["project_name"]) == ("team-1", "proj-guid", "Alpha")
        assert result.paths[1] == "/myorg/_apis/projects/proj-guid/teams"

    def test_team_members_lift_the_identity_id_to_the_row_root(self):
        result = _driver().run(
            "team_members",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": "team-1", "name": "QA"}]}),
                _response({"value": [{"isTeamAdmin": True, "identity": {"id": "identity-1", "displayName": "Ada"}}]}),
                _response({"value": []}),
                _response({"value": []}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        # identity_id and team_id are the composite primary key, so both must be present.
        assert (row["identity_id"], row["team_id"], row["team_name"]) == ("identity-1", "team-1", "QA")
        assert row["project_id"] == "proj-guid"
        assert result.paths[2] == "/myorg/_apis/projects/proj-guid/teams/team-1/members"


class TestPipelineEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    def test_pipelines_paginate_via_header_token_and_carry_the_project(self):
        result = _driver().run(
            "pipelines",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 3, "name": "deploy"}]}, continuation_header="tok1"),
                _response({"value": [{"id": 4, "name": "release"}]}),
            ],
        )

        assert result.raised is None
        # project_id is half the composite primary key, so it must be present.
        assert [(row["id"], row["project_id"]) for row in result.rows] == [(3, "proj-guid"), (4, "proj-guid")]
        assert result.paths[1] == "/myorg/proj-guid/_apis/pipelines"
        assert result.requests[2].param("continuationToken") == "tok1"

    def test_pipeline_runs_follow_a_continuation_token_without_asking_for_a_page_size(self):
        # The listing documents no paging parameters. Reading one response would cap the table
        # at whatever the vendor returns in it, and sending $top could shorten that response.
        result = _driver().run(
            "pipeline_runs",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 3, "name": "deploy"}]}),
                _response({"value": [{"id": 91}]}, continuation_header="tok1"),
                _response({"value": [{"id": 92}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [91, 92]
        assert result.requests[2].param("$top") is None
        assert result.requests[3].param("continuationToken") == "tok1"

    def test_pipeline_runs_skip_a_pipeline_without_an_id(self):
        # Requesting one anyway would build a path with a literal {pipelineId} placeholder.
        result = _driver().run(
            "pipeline_runs",
            [_response(self.PROJECTS), _response({"value": [{"name": "deploy"}]})],
        )

        assert result.raised is None
        assert result.items == []
        assert len(result.requests) == 2


class TestWorkItemLookupEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}
    TYPES = {"value": [{"name": "User Story", "referenceName": "Microsoft.VSTS.WorkItemTypes.UserStory"}]}

    def test_work_item_types_carry_the_project_reference(self):
        result = _driver().run("work_item_types", [_response(self.PROJECTS), _response(self.TYPES)])

        assert result.raised is None
        row = result.rows[0]
        # project_id is half the composite primary key, so it must be present.
        assert (row["referenceName"], row["project_id"], row["project_name"]) == (
            "Microsoft.VSTS.WorkItemTypes.UserStory",
            "proj-guid",
            "Alpha",
        )
        assert result.paths[1] == "/myorg/proj-guid/_apis/wit/workitemtypes"

    def test_work_item_type_states_fan_out_over_types_and_encode_the_type_name(self):
        result = _driver().run(
            "work_item_type_states",
            [
                _response(self.PROJECTS),
                _response(self.TYPES),
                _response({"value": [{"name": "Active", "color": "007acc", "category": "InProgress"}]}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
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
        assert result.paths[2] == "/myorg/proj-guid/_apis/wit/workitemtypes/User%20Story/states"

    def test_classification_nodes_request_the_full_tree_depth(self):
        result = _driver().run(
            "work_item_classification_nodes",
            [_response(self.PROJECTS), _response({"value": []})],
        )

        assert result.raised is None
        assert result.paths[1] == "/myorg/proj-guid/_apis/wit/classificationnodes"
        # Without $depth the API answers with the two roots and no children at all.
        assert result.requests[1].param("$depth") == str(CLASSIFICATION_NODE_DEPTH)

    def test_work_iterations_fan_out_over_teams(self):
        result = _driver().run(
            "work_iterations",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": "team-1", "name": "QA"}]}),
                _response({"value": [{"id": "iter-guid", "name": "Sprint 1", "path": "Alpha\\Sprint 1"}]}),
                _response({"value": []}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        # team_id is half the composite primary key: teams share one project iteration tree,
        # so the same iteration id comes back for every team subscribed to it.
        assert (row["id"], row["team_id"], row["team_name"], row["project_id"]) == (
            "iter-guid",
            "team-1",
            "QA",
            "proj-guid",
        )
        assert result.paths[2] == "/myorg/proj-guid/team-1/_apis/work/teamsettings/iterations"


class TestFlattenClassificationNodes:
    PROJECT = {"id": "proj-guid", "name": "Alpha"}

    def test_warns_when_the_tree_is_cut_off_at_the_requested_depth(self):
        logger = mock.MagicMock()

        _flatten_classification_nodes({"id": 1, "hasChildren": True}, self.PROJECT, logger)

        logger.warning.assert_called_once()


class TestBuildEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    def test_build_definitions_carry_the_project_reference(self):
        result = _driver().run(
            "build_definitions",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 7, "name": "core-ci", "createdDate": "2024-01-02T03:04:05Z"}]}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        # project_id is half the composite primary key, so it must be present.
        assert (row["id"], row["project_id"], row["project_name"]) == (7, "proj-guid", "Alpha")
        assert result.paths[1] == "/myorg/Alpha/_apis/build/definitions"
        assert result.requests[1].param("queryOrder") == "lastModifiedAscending"

    def test_build_timeline_records_carry_the_build_they_describe(self):
        result = _driver().run(
            "build_timeline_records",
            [
                _response(self.PROJECTS),
                _response(
                    {"value": [{"id": 41, "queueTime": "2024-01-02T03:04:05Z", "finishTime": "2024-01-02T03:20:00Z"}]}
                ),
                _response({"id": "timeline-1", "records": [{"id": "rec-1", "type": "Job", "result": "failed"}]}),
            ],
        )

        assert result.raised is None
        row = result.rows[0]
        # build_id is half the composite primary key; the queue time partitions and the
        # finish time is the watermark, and only the parent build carries either.
        assert (row["id"], row["build_id"], row["timeline_id"]) == ("rec-1", 41, "timeline-1")
        assert row["build_queue_time"] == "2024-01-02T03:04:05Z"
        assert row["build_finish_time"] == "2024-01-02T03:20:00Z"
        assert row["project_name"] == "Alpha"
        assert result.paths[2] == "/myorg/Alpha/_apis/build/builds/41/timeline"


class TestReleaseEndpoints:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("releases", "/myorg/Alpha/_apis/release/releases"),
            ("release_deployments", "/myorg/Alpha/_apis/release/deployments"),
        ],
    )
    def test_release_endpoints_are_read_from_the_release_host(self, endpoint, path):
        result = _driver().run(
            endpoint,
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 5, "name": "Release-5"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        row = result.rows[0]
        assert (row["id"], row["project_id"], row["project_name"]) == (5, "proj-guid", "Alpha")
        # Release Management is served from its own host; dev.azure.com 404s these routes.
        assert result.urls[0].startswith("https://dev.azure.com/")
        assert result.urls[1].startswith(f"{AZURE_DEVOPS_RELEASE_BASE_URL}/")
        assert result.paths[1] == path
        assert result.requests[1].param("queryOrder") == "ascending"


class TestTestRunEndpoint:
    PROJECTS = {"value": [{"id": "proj-guid", "name": "Alpha"}]}

    def test_full_refresh_walks_the_unfiltered_listing(self):
        result = _driver().run(
            "test_runs",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 3, "totalTests": 10, "passedTests": 9}]}),
                _response({"value": []}),
            ],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows[0]["project_id"] == "proj-guid"
        assert result.requests[1].param("$skip") == "0"
        assert result.requests[1].param("minLastUpdatedDate") is None

    def test_incremental_sends_both_window_bounds(self):
        # Both bounds are mandatory on the filtered query and the span may not exceed
        # the cap, so sending minLastUpdatedDate alone is rejected.
        since = datetime.now(UTC) - timedelta(days=2)
        result = _driver().run(
            "test_runs",
            [
                _response(self.PROJECTS),
                _response({"value": [{"id": 3}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=since,
        )

        assert result.raised is None
        query = result.requests[1]
        min_last_updated = query.param("minLastUpdatedDate")
        max_last_updated = query.param("maxLastUpdatedDate")
        assert min_last_updated == _format_datetime(since)
        assert max_last_updated is not None
        window_start = datetime.fromisoformat(min_last_updated.replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(max_last_updated.replace("Z", "+00:00"))
        assert window_end - window_start <= TEST_RUN_WINDOW
        assert query.param("$skip") is None


class TestAzureDevOpsSourceResponse:
    def test_pull_requests_are_desc_sorted(self):
        result = _driver().run("pull_requests", [_response({"value": []})])
        assert result.response is not None
        assert result.response.sort_mode == "desc"


class TestApiVersionDispatch:
    def test_wire_api_version_rejects_unknown_label(self):
        # A silent fallthrough would send no api-version and track whatever the vendor defaults to.
        with pytest.raises(ValueError):
            wire_api_version("nope")

    @pytest.mark.parametrize("version, wire", [(AZURE_DEVOPS_VERSION_LEGACY, "7.1"), (AZURE_DEVOPS_VERSION_7_2, "7.2")])
    def test_get_rows_sends_pinned_api_version_on_the_wire(self, version, wire):
        result = _driver().run("projects", [_response({"value": []})], api_version=version)

        assert result.raised is None
        assert result.requests[0].param("api-version") == wire
