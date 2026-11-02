import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud import (
    DagsterCloudResumeConfig,
    _build_runs_filter,
    _epoch_to_iso,
    _expand_metric_entries,
    _flatten_reporting_entity,
    _make_fanout_request,
    _make_insights_request,
    _to_epoch_seconds,
    build_graphql_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.settings import (
    DAGSTER_CLOUD_ENDPOINTS,
    DAGSTER_CLOUD_INSIGHTS_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source import DagsterCloudSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dagstercloud import (
    DagsterCloudSourceConfig,
)

# 2024-01-01T00:00:00Z
EPOCH_2024 = 1704067200.0
ISO_2024 = "2024-01-01T00:00:00.000000+00:00"

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud"


def _driver() -> SourceDriver:
    return SourceDriver(
        DagsterCloudSource(), DagsterCloudSourceConfig(organization="org", deployment="prod", api_token="tok")
    )


def _gql_response(response_field: str, container: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {response_field: container}})


def _runs_container(run_ids: list[str]) -> dict[str, Any]:
    return {
        "__typename": "Runs",
        "results": [
            {"runId": rid, "status": "SUCCESS", "creationTime": EPOCH_2024, "updateTime": EPOCH_2024} for rid in run_ids
        ],
    }


def _assets_container(ids: list[str], cursor: str | None) -> dict[str, Any]:
    return {
        "__typename": "AssetConnection",
        "cursor": cursor,
        "nodes": [{"id": i, "key": {"path": [i]}} for i in ids],
    }


def _manager(saved: DagsterCloudResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.load_state.return_value = saved
    return manager


class TestBuildGraphqlUrl:
    @parameterized.expand(
        [
            ("space", "my org", "prod"),
            ("host_injection", "evil.com/x", "prod"),
            ("path_traversal", "../etc", "prod"),
            ("empty_org", "", "prod"),
            ("slash_in_deployment", "org", "prod/../admin"),
            ("dot_in_org", "a.b", "prod"),
        ]
    )
    def test_rejects_unsafe_values(self, _name: str, org: str, deployment: str) -> None:
        # The org/deployment build the *.dagster.cloud URL the stored token is sent to; anything
        # that isn't a plain slug could redirect the credential to another host.
        with pytest.raises(ValueError):
            build_graphql_url(org, deployment)


class TestTimestampConversion:
    @parameterized.expand([("string", "not-a-number"), ("none", None)])
    def test_epoch_to_iso_passes_through_non_numeric(self, _name: str, value: Any) -> None:
        assert _epoch_to_iso(value) == value

    @parameterized.expand(
        [
            ("float", EPOCH_2024, EPOCH_2024),
            ("datetime_utc", datetime(2024, 1, 1, tzinfo=UTC), EPOCH_2024),
            ("naive_datetime_treated_utc", datetime(2024, 1, 1), EPOCH_2024),
            ("date", date(2024, 1, 1), EPOCH_2024),
            ("iso_offset", "2024-01-01T00:00:00+00:00", EPOCH_2024),
            ("iso_zulu", "2024-01-01T00:00:00Z", EPOCH_2024),
            ("none", None, None),
            ("garbage", "soon", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: float | None) -> None:
        assert _to_epoch_seconds(value) == expected


class TestBuildRunsFilter:
    @parameterized.expand(
        [
            ("update_default", "updateTime", EPOCH_2024, {"updatedAfter": EPOCH_2024}),
            ("none_field_defaults_to_updated", None, EPOCH_2024, {"updatedAfter": EPOCH_2024}),
            ("creation_uses_created", "creationTime", EPOCH_2024, {"createdAfter": EPOCH_2024}),
            ("no_value", "updateTime", None, None),
        ]
    )
    def test_filter(self, _name: str, field: str | None, value: float | None, expected: dict | None) -> None:
        assert _build_runs_filter(field, value) == expected


class TestPagination:
    def test_redirect_raises_without_retry(self) -> None:
        # Redirects are pinned off; a 30x must fail fast (not spin through the retry budget).
        result = _driver().run("runs", [ScriptedResponse(status=301)])

        assert isinstance(result.raised, Exception)
        assert "unexpected redirect" in str(result.raised)
        assert len(result.requests) == 1

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "runs",
            [_gql_response("runsOrError", _runs_container(["r9"]))],
            resume_state=DagsterCloudResumeConfig(cursor="saved"),
        )

        assert result.raised is None
        assert result.requests[0].json()["variables"]["cursor"] == "saved"

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_error_typename_raises(self) -> None:
        result = _driver().run("runs", [_gql_response("runsOrError", {"__typename": "PythonError", "message": "boom"})])

        assert isinstance(result.raised, Exception)
        assert "PythonError" in str(result.raised)

    def test_incremental_runs_send_server_filter(self) -> None:
        # The whole point of incremental: the watermark must reach the API as a server-side filter,
        # not be applied client-side after fetching everything.
        result = _driver().run(
            "runs",
            [_gql_response("runsOrError", _runs_container([]))],
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="updateTime",
        )

        assert result.raised is None
        assert result.requests[0].json()["variables"]["filter"] == {"updatedAfter": EPOCH_2024}


class TestValidateCredentials:
    def test_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": {"__typename": "Query"}})]) as network:
            assert validate_credentials("org", "prod", "tok") == (True, None)
        # Validation sends the same credentialed header — same redaction/no-redirect posture.
        session_kwargs = network.session_options[0]
        assert session_kwargs["redact_values"] == ("tok",)
        assert session_kwargs["allow_redirects"] is False

    def test_redirect_fails_validation(self) -> None:
        with scripted_network([ScriptedResponse(status=302)]):
            ok, error = validate_credentials("org", "prod", "tok")
        assert ok is False
        assert error is not None and "redirect" in error

    def test_invalid_slug_fails_before_request(self) -> None:
        ok, error = validate_credentials("bad host", "prod", "tok")
        assert ok is False
        assert error is not None


class TestEndpointCatalog:
    def test_incremental_endpoints_are_the_ones_with_server_side_filters(self) -> None:
        # RunsFilter.updatedAfter, InstigationState.ticks(afterTimestamp), the asset event
        # resolvers' afterTimestampMillis and the Insights selector's after/before genuinely filter
        # server-side; run_logs has no filter of its own but narrows its parent run walk with
        # RunsFilter.updatedAfter. Every other endpoint would walk full history on an
        # "incremental" run, so it must stay full-refresh.
        incremental = {name for name, cfg in DAGSTER_CLOUD_ENDPOINTS.items() if cfg.supports_incremental}
        assert incremental == {
            "runs",
            "instigation_ticks",
            "asset_materializations",
            "asset_observations",
            "run_logs",
            "insights_job_metrics",
            "insights_asset_metrics",
            "insights_deployment_metrics",
        }

    def test_fanout_primary_keys_carry_their_parent(self) -> None:
        # A fan-out child aggregates rows from every parent, so a key that is only unique per
        # parent seeds duplicates the merge then multi-matches on every later sync.
        for name, cfg in DAGSTER_CLOUD_ENDPOINTS.items():
            if cfg.fan_out is None or not cfg.fan_out.include_from_parent:
                continue
            assert set(cfg.fan_out.include_from_parent) & set(cfg.primary_keys), name


def _with_batch_size(endpoint_name: str, batch_size: int) -> Any:
    endpoint_config = DAGSTER_CLOUD_ENDPOINTS[endpoint_name]
    assert endpoint_config.fan_out is not None
    return replace(endpoint_config, fan_out=replace(endpoint_config.fan_out, batch_size=batch_size))


def _route(
    handlers: dict[str, ScriptedResponse | list[ScriptedResponse]],
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        match = re.search(r"query (\w+)", request.json()["query"])
        assert match is not None
        operation = match.group(1)
        handler = handlers[operation]
        return handler.pop(0) if isinstance(handler, list) else handler

    return respond


def _variables(result: DriveResult, operation: str) -> list[dict[str, Any]]:
    return [
        request.json()["variables"]
        for request in result.requests
        if re.search(rf"query {operation}\b", request.json()["query"])
    ]


def _repositories_response(names: list[tuple[str, str, str]]) -> ScriptedResponse:
    return _gql_response(
        "repositoriesOrError",
        {
            "__typename": "RepositoryConnection",
            "nodes": [
                {"id": repo_id, "name": name, "location": {"name": location}} for repo_id, name, location in names
            ],
        },
    )


def _assets_page(ids: list[str], cursor: str | None) -> ScriptedResponse:
    return _gql_response("assetsOrError", _assets_container(ids, cursor))


def _materializations_response(timestamps_millis: list[str]) -> ScriptedResponse:
    return _gql_response(
        "assetOrError",
        {
            "__typename": "Asset",
            "assetMaterializations": [
                {"runId": f"run-{ts}", "timestamp": ts, "stepKey": "step", "partition": None}
                for ts in timestamps_millis
            ],
        },
    )


def _ticks_response(timestamps: list[float]) -> ScriptedResponse:
    return _gql_response(
        "instigationStateOrError",
        {
            "__typename": "InstigationState",
            "ticks": [
                {"tickId": str(int(ts)), "status": "SUCCESS", "timestamp": ts, "endTimestamp": ts + 1}
                for ts in timestamps
            ],
        },
    )


class TestRepositoryFanOut:
    def test_one_child_request_per_repository_with_parent_fields_injected(self) -> None:
        result = _driver().run(
            "schedules",
            _route(
                {
                    "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                    "RepositorySchedules": [
                        _gql_response("schedulesOrError", {"__typename": "Schedules", "results": [{"name": "daily"}]}),
                        _gql_response("schedulesOrError", {"__typename": "Schedules", "results": [{"name": "hourly"}]}),
                    ],
                }
            ),
        )

        assert result.raised is None
        # Each row has to name its repository: the primary key is only unique with it.
        assert result.rows == [
            {"name": "daily", "repositoryName": "repo_a", "repositoryLocationName": "loc_a"},
            {"name": "hourly", "repositoryName": "repo_b", "repositoryLocationName": "loc_b"},
        ]
        child_variables = _variables(result, "RepositorySchedules")
        assert [v["repositoryName"] for v in child_variables] == ["repo_a", "repo_b"]
        # One parent finished per checkpoint, so a resume restarts at the next repository.
        assert result.saved_states == [
            DagsterCloudResumeConfig(parents_done=1),
            DagsterCloudResumeConfig(parents_done=2),
        ]

    def test_repository_deleted_mid_sync_is_skipped(self) -> None:
        # The parent list is read before the children, so a repository removed in between must
        # not fail the whole sync.
        result = _driver().run(
            "sensors",
            _route(
                {
                    "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                    "RepositorySensors": [
                        _gql_response("sensorsOrError", {"__typename": "RepositoryNotFoundError", "message": "gone"}),
                        _gql_response("sensorsOrError", {"__typename": "Sensors", "results": [{"name": "s"}]}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["s"]

    def test_resume_skips_finished_parents(self) -> None:
        result = _driver().run(
            "schedules",
            _route(
                {
                    "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                    "RepositorySchedules": _gql_response(
                        "schedulesOrError", {"__typename": "Schedules", "results": []}
                    ),
                }
            ),
            resume_state=DagsterCloudResumeConfig(parents_done=1),
        )

        assert result.raised is None
        child_variables = _variables(result, "RepositorySchedules")
        assert [v["repositoryName"] for v in child_variables] == ["repo_b"]


class TestTwoLevelFanOut:
    def test_incremental_ticks_send_seconds_float_watermark(self) -> None:
        result = _driver().run(
            "instigation_ticks",
            _route(
                {
                    "Repositories": _repositories_response([("repo-id-1", "repo_a", "loc_a")]),
                    "RepositoryInstigationStates": _gql_response(
                        "instigationStatesOrError",
                        {
                            "__typename": "InstigationStates",
                            "results": [{"id": "c", "selectorId": "s", "name": "daily"}],
                        },
                    ),
                    "InstigationTicks": _ticks_response([]),
                }
            ),
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="timestamp",
        )

        assert result.raised is None
        tick_variables = _variables(result, "InstigationTicks")[0]
        # ticks(afterTimestamp:) is a Float of epoch seconds, not the asset resolvers' millis string.
        assert tick_variables["afterTimestamp"] == EPOCH_2024


class TestAssetEventFanOut:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_a_window_that_does_not_advance_fails_the_sync(self) -> None:
        # An API that ignored beforeTimestampMillis would replay one page forever. Failing beats
        # truncating: sort_mode is "desc", so a silently short parent still commits a watermark
        # above the events it skipped, and no later sync would ask for them.
        page = _materializations_response(["1700000001000", "1700000001000"])
        result = _driver().run(
            "asset_materializations",
            _route(
                {
                    "PaginatedAssets": _assets_page(["a1"], cursor=None),
                    "AssetMaterializations": [page, page],
                }
            ),
        )

        assert isinstance(result.raised, Exception)
        assert "page window did not advance" in str(result.raised)


class TestBatchedFanOut:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch.dict(DAGSTER_CLOUD_ENDPOINTS, {"asset_nodes": _with_batch_size("asset_nodes", 2)})
    def test_asset_nodes_batches_keys_and_reads_a_bare_root_list(self) -> None:
        # assetNodes returns [AssetNode!]! rather than an OrError union, and takes the keys in
        # one list — so the walk batches parents instead of issuing a request each.
        node_response = ScriptedResponse(
            json={"data": {"assetNodes": [{"id": "n1", "groupName": "default"}, {"id": "n2", "groupName": "default"}]}}
        )
        result = _driver().run(
            "asset_nodes",
            _route(
                {
                    "PaginatedAssets": [_assets_page(["a1", "a2"], cursor="p2"), _assets_page(["a3"], cursor=None)],
                    "AssetNodes": [node_response, node_response],
                }
            ),
        )

        assert result.raised is None
        node_variables = _variables(result, "AssetNodes")
        # Parents are collected up to batch_size, so the first two assets go out together and
        # the trailing one follows in a final partial batch.
        assert node_variables[0]["assetKeys"] == [{"path": ["a1"]}, {"path": ["a2"]}]
        assert node_variables[1]["assetKeys"] == [{"path": ["a3"]}]
        assert len(result.rows) == 4
        assert result.saved_states == [
            DagsterCloudResumeConfig(parents_done=2),
            DagsterCloudResumeConfig(parents_done=3),
        ]


class TestFanOutRouting:
    def test_unknown_fanout_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Dagster Cloud fan-out endpoint"):
            list(_make_fanout_request("org", "prod", "tok", "runs", MagicMock(), _manager()))


class TestCursorProgress:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_a_cursor_that_does_not_advance_fails_the_sync(self) -> None:
        # Nothing else bounds the cursor walk, so a repeated cursor would re-request one page
        # until the activity timed out.
        page = _gql_response("runsOrError", _runs_container(["r1", "r1"]))
        result = _driver().run("runs", [page, page])

        assert isinstance(result.raised, Exception)
        assert "pagination cursor did not advance" in str(result.raised)


def _deployments_response(full: list[str], branch: list[str]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                "fullDeployments": [{"deploymentId": name, "isBranchDeployment": False} for name in full],
                "branchDeployments": {"nodes": [{"deploymentId": name, "isBranchDeployment": True} for name in branch]},
            }
        }
    )


class TestDeployments:
    def test_branch_deployment_cap_is_reported(self) -> None:
        # The resolver offers no cursor past its limit, so a response at the cap is the only
        # signal that deployments were left out.
        cap = DAGSTER_CLOUD_ENDPOINTS["deployments"].extra_list_fields[0].truncation_cap
        assert cap is not None
        logger = MagicMock()

        result = _driver().run(
            "deployments", [_deployments_response([], [f"pr-{i}" for i in range(cap)])], logger=logger
        )

        assert result.raised is None
        assert "branchDeployments" in logger.warning.call_args[0][0]


def _run_logs_response(messages: list[str], cursor: str | None, has_more: bool) -> ScriptedResponse:
    return _gql_response(
        "logsForRun",
        {
            "__typename": "EventConnection",
            "cursor": cursor,
            "hasMore": has_more,
            "events": [
                {
                    "eventTypename": "LogMessageEvent",
                    "runId": "r1",
                    "message": message,
                    "timestamp": "1704067200000",
                }
                for message in messages
            ],
        },
    )


class TestRunLogFanOut:
    @parameterized.expand([("incremental", EPOCH_2024), ("full_refresh", None)])
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_the_parent_run_walk_is_bounded_at_both_ends(self, _name: str, watermark: float | None) -> None:
        # logsForRun has no timestamp filter of its own; without narrowing the parent walk every
        # incremental sync would re-read the whole log of every run the deployment ever had.
        before = datetime.now(tz=UTC).timestamp()
        result = _driver().run(
            "run_logs",
            _route(
                {
                    "PaginatedRuns": [_gql_response("runsOrError", _runs_container(["r1"]))],
                    "RunLogs": [_run_logs_response(["a"], cursor=None, has_more=False)],
                }
            ),
            incremental_field="runUpdateTime" if watermark is not None else None,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        runs_filter = _variables(result, "PaginatedRuns")[0]["filter"]
        assert runs_filter.get("updatedAfter") == watermark
        # The walk pages backwards from the newest run, so a run that moves after it started
        # would never be fetched while the watermark advanced past it.
        assert before <= runs_filter["updatedBefore"] <= datetime.now(tz=UTC).timestamp()
        # The child checkpoints on the parent's update time, so the parent has to put it on
        # every row rather than leave the row's own event timestamp as the cursor.
        assert result.rows[0]["runUpdateTime"] == ISO_2024

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_a_cursor_that_does_not_advance_fails_the_sync(self) -> None:
        result = _driver().run(
            "run_logs",
            _route(
                {
                    "PaginatedRuns": [_gql_response("runsOrError", _runs_container(["r1"]))],
                    "RunLogs": [_run_logs_response(["a"], cursor="c1", has_more=True)] * 2,
                }
            ),
        )

        assert isinstance(result.raised, Exception)
        assert "page cursor did not advance" in str(result.raised)

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    def test_a_run_deleted_mid_sync_is_skipped(self) -> None:
        # The run list is read before the logs, so a run purged in between must not fail the sync.
        result = _driver().run(
            "run_logs",
            _route(
                {
                    "PaginatedRuns": [_gql_response("runsOrError", _runs_container(["r1"]))],
                    "RunLogs": _gql_response("logsForRun", {"__typename": "RunNotFoundError", "message": "gone"}),
                }
            ),
        )

        assert result.raised is None
        assert result.rows == []


class TestReportingEntities:
    @parameterized.expand(
        [
            (
                "job",
                {"__typename": "ReportingJob", "codeLocationName": "loc", "repositoryName": "repo", "jobName": "etl"},
                "loc/repo/etl",
            ),
            ("asset", {"__typename": "ReportingAsset", "assetKey": {"path": ["a", "b"]}}, "a/b"),
            ("deployment", {"__typename": "DagsterCloudDeployment", "deploymentId": 7}, "7"),
        ]
    )
    def test_entity_id_identifies_the_entity(self, _name: str, entity: dict[str, Any], expected: str) -> None:
        # The id is half the primary key, so two different entities collapsing onto one would
        # silently overwrite each other's measurements on every merge.
        entity_id, columns = _flatten_reporting_entity(entity)
        assert entity_id == expected
        assert "__typename" not in columns


class TestInsightsExpansion:
    def test_buckets_expand_against_the_shared_timestamps(self) -> None:
        # The response reports the bucket starts once and each entity's values positionally
        # against them, so a misalignment would file every measurement under the wrong day.
        entries = [
            {
                "entity": {"__typename": "DagsterCloudDeployment", "deploymentId": 7, "deploymentName": "prod"},
                "values": [1.5, None, 3.5],
            }
        ]
        rows = _expand_metric_entries("dagster_credits", entries, [EPOCH_2024, EPOCH_2024 + 86400, EPOCH_2024 + 172800])

        # A null bucket means the metric reported nothing, and a row per empty bucket per entity
        # would dwarf the measurements.
        assert [(row["timestamp"], row["value"]) for row in rows] == [
            (ISO_2024, 1.5),
            (_epoch_to_iso(EPOCH_2024 + 172800), 3.5),
        ]
        assert rows[0]["entityId"] == "7"
        assert rows[0]["deploymentName"] == "prod"
        assert rows[0]["metricName"] == "dagster_credits"

    def test_an_entity_with_no_id_is_dropped(self) -> None:
        entries = [{"entity": {"__typename": "ReportingAssetSelection", "selection": "*"}, "values": [1.0]}]
        assert _expand_metric_entries("m", entries, [EPOCH_2024]) == []


def _metric_types_response(field: str, names: list[str]) -> ScriptedResponse:
    return _gql_response(field, {"__typename": "MetricTypeList", "metricTypes": [{"metricName": n} for n in names]})


def _metrics_response(field: str, entity_ids: list[int], timestamps: list[float]) -> ScriptedResponse:
    return _gql_response(
        field,
        {
            "__typename": "ReportingMetrics",
            "timestamps": timestamps,
            "metrics": [
                {
                    "entity": {"__typename": "DagsterCloudDeployment", "deploymentId": entity_id},
                    "values": [1.0] * len(timestamps),
                }
                for entity_id in entity_ids
            ],
        },
    )


class TestInsightsRequests:
    @parameterized.expand([("incremental", EPOCH_2024), ("full_refresh", None)])
    def test_the_watermark_bounds_the_reporting_window(self, _name: str, watermark: float | None) -> None:
        result = _driver().run(
            "insights_deployment_metrics",
            _route(
                {
                    "MetricTypesForDeployment": _metric_types_response("metricTypesForDeployment", ["dagster_credits"]),
                    "ReportingMetricsByDeployment": _metrics_response(
                        "reportingMetricsByDeployment", [7], [EPOCH_2024]
                    ),
                }
            ),
            incremental_field="timestamp" if watermark is not None else None,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        selector = _variables(result, "ReportingMetricsByDeployment")[0]["metricsSelector"]
        if watermark is None:
            # A first sync reaches back as far as Dagster+ reports, not to the epoch.
            assert selector["before"] - selector["after"] == pytest.approx(DAGSTER_CLOUD_INSIGHTS_LOOKBACK_DAYS * 86400)
        else:
            assert selector["after"] == watermark

    def test_resume_skips_the_metrics_already_synced(self) -> None:
        result = _driver().run(
            "insights_deployment_metrics",
            _route(
                {
                    "MetricTypesForDeployment": _metric_types_response(
                        "metricTypesForDeployment", ["dagster_credits", "execution_time_ms"]
                    ),
                    "ReportingMetricsByDeployment": _metrics_response(
                        "reportingMetricsByDeployment", [7], [EPOCH_2024]
                    ),
                }
            ),
            resume_state=DagsterCloudResumeConfig(parents_done=1),
        )

        assert result.raised is None
        metric_variables = _variables(result, "ReportingMetricsByDeployment")
        assert [v["metricsSelector"]["metricName"] for v in metric_variables] == ["execution_time_ms"]

    @patch(f"{MODULE}.DAGSTER_CLOUD_INSIGHTS_ENTITY_LIMIT", 2)
    def test_an_entity_list_at_the_cap_is_reported(self) -> None:
        # The resolver bounds its entity list with that filter limit and offers no cursor, so a
        # response at the cap is the only signal that entities were left out.
        logger = MagicMock()
        result = _driver().run(
            "insights_deployment_metrics",
            _route(
                {
                    "MetricTypesForDeployment": _metric_types_response("metricTypesForDeployment", ["dagster_credits"]),
                    "ReportingMetricsByDeployment": _metrics_response(
                        "reportingMetricsByDeployment", [7, 8], [EPOCH_2024]
                    ),
                }
            ),
            logger=logger,
        )

        assert result.raised is None
        assert _variables(result, "ReportingMetricsByDeployment")[0]["metricsFilter"]["limit"] == 2
        assert "dagster_credits" in logger.warning.call_args[0][0]

    def test_a_token_without_insights_fails_naming_the_resolver(self) -> None:
        # Insights is a Dagster+ entitlement; an empty table would read as "no metrics" rather
        # than "your token cannot see them".
        result = _driver().run(
            "insights_deployment_metrics",
            _route(
                {
                    "MetricTypesForDeployment": _gql_response(
                        "metricTypesForDeployment", {"__typename": "UnauthorizedError", "message": "not permitted"}
                    )
                }
            ),
        )

        assert isinstance(result.raised, Exception)
        assert "metricTypesForDeployment returned UnauthorizedError" in str(result.raised)

    def test_unknown_insights_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Dagster Cloud insights endpoint"):
            list(_make_insights_request("org", "prod", "tok", "runs", MagicMock(), _manager()))


class TestOrganizationEndpoints:
    def test_a_token_without_organization_access_fails_naming_the_resolver(self) -> None:
        result = _driver().run(
            "users",
            [_gql_response("usersOrError", {"__typename": "UnauthorizedError", "message": "not permitted"})],
        )

        assert isinstance(result.raised, Exception)
        assert "usersOrError returned UnauthorizedError" in str(result.raised)
