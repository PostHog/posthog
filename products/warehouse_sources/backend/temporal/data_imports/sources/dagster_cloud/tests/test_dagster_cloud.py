import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud import (
    DagsterCloudResumeConfig,
    _build_runs_filter,
    _epoch_to_iso,
    _make_fanout_request,
    _make_paginated_request,
    _to_epoch_seconds,
    build_graphql_url,
    dagster_cloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.settings import (
    DAGSTER_CLOUD_ENDPOINTS,
)

# 2024-01-01T00:00:00Z
EPOCH_2024 = 1704067200.0
ISO_2024 = "2024-01-01T00:00:00.000000+00:00"

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud"


def _gql_response(response_field: str, container: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {"data": {response_field: container}}
    return response


def _runs_container(run_ids: list[str]) -> dict[str, Any]:
    return {
        "__typename": "Runs",
        "results": [{"runId": rid, "status": "SUCCESS", "creationTime": EPOCH_2024} for rid in run_ids],
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
    def test_valid(self) -> None:
        assert build_graphql_url("my-org", "prod") == "https://my-org.dagster.cloud/prod/graphql"

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
    def test_epoch_to_iso_is_fixed_precision(self) -> None:
        assert _epoch_to_iso(EPOCH_2024) == ISO_2024

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
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_row_cursor_paginates_and_checkpoints(self, mock_session_cls: MagicMock) -> None:
        # A full page continues from the last row's runId; a short page ends the walk.
        session = MagicMock()
        session.post.side_effect = [
            _gql_response("runsOrError", _runs_container(["r1", "r2"])),
            _gql_response("runsOrError", _runs_container(["r3"])),
        ]
        mock_session_cls.return_value = session
        manager = _manager()

        pages = list(_make_paginated_request("org", "prod", "tok", "runs", MagicMock(), manager))

        assert [row["runId"] for page in pages for row in page] == ["r1", "r2", "r3"]
        # Timestamps are normalized to ISO on the way out so partitioning can read them.
        assert pages[0][0]["creationTime"] == ISO_2024
        # Only the non-final page checkpoints, pointing at the next page's cursor.
        manager.save_state.assert_called_once_with(DagsterCloudResumeConfig(cursor="r2"))
        assert session.post.call_count == 2
        # The token rides a custom header the sample scrubber doesn't know, so it must be redacted
        # by value, and redirects must stay off so a 30x can't forward the header cross-host.
        session_kwargs = mock_session_cls.call_args.kwargs
        assert session_kwargs["redact_values"] == ("tok",)
        assert session_kwargs["allow_redirects"] is False

    @patch(f"{MODULE}.make_tracked_session")
    def test_redirect_raises_without_retry(self, mock_session_cls: MagicMock) -> None:
        # Redirects are pinned off; a 30x must fail fast (not spin through the retry budget).
        session = MagicMock()
        response = MagicMock()
        response.status_code = 301
        session.post.return_value = response
        mock_session_cls.return_value = session

        with pytest.raises(Exception, match="unexpected redirect"):
            list(_make_paginated_request("org", "prod", "tok", "runs", MagicMock(), _manager()))

        assert session.post.call_count == 1

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_connection_cursor_mode_uses_connection_cursor(self, mock_session_cls: MagicMock) -> None:
        # assetsOrError returns its next cursor on the connection object, not from the last row.
        session = MagicMock()
        session.post.side_effect = [
            _gql_response("assetsOrError", _assets_container(["a1", "a2"], cursor="page2")),
            _gql_response("assetsOrError", _assets_container(["a3"], cursor=None)),
        ]
        mock_session_cls.return_value = session
        manager = _manager()

        list(_make_paginated_request("org", "prod", "tok", "assets", MagicMock(), manager))

        manager.save_state.assert_called_once_with(DagsterCloudResumeConfig(cursor="page2"))

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        captured: list[Any] = []

        def side_effect(*_args: object, **kwargs: object) -> MagicMock:
            payload = cast(dict, kwargs["json"])
            captured.append(payload["variables"].get("cursor"))
            return _gql_response("runsOrError", _runs_container(["r9"]))

        session.post.side_effect = side_effect
        mock_session_cls.return_value = session

        list(
            _make_paginated_request(
                "org", "prod", "tok", "runs", MagicMock(), _manager(DagsterCloudResumeConfig(cursor="saved"))
            )
        )

        assert captured[0] == "saved"

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_error_typename_raises(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.return_value = _gql_response("runsOrError", {"__typename": "PythonError", "message": "boom"})
        mock_session_cls.return_value = session

        with pytest.raises(Exception, match="PythonError"):
            list(_make_paginated_request("org", "prod", "tok", "runs", MagicMock(), _manager()))

    @patch(f"{MODULE}.make_tracked_session")
    def test_incremental_runs_send_server_filter(self, mock_session_cls: MagicMock) -> None:
        # The whole point of incremental: the watermark must reach the API as a server-side filter,
        # not be applied client-side after fetching everything.
        session = MagicMock()
        captured: list[Any] = []

        def side_effect(*_args: object, **kwargs: object) -> MagicMock:
            payload = cast(dict, kwargs["json"])
            captured.append(payload["variables"].get("filter"))
            return _gql_response("runsOrError", _runs_container([]))

        session.post.side_effect = side_effect
        mock_session_cls.return_value = session

        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="runs",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="updateTime",
        )
        list(cast(Iterable[Any], response.items()))

        assert captured[0] == {"updatedAfter": EPOCH_2024}


class TestSourceResponse:
    def test_runs_response_is_incremental_desc_partitioned(self) -> None:
        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="runs",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.primary_keys == ["runId"]
        # runsOrError returns newest-first with no ascending option — declaring asc would corrupt
        # the incremental watermark.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["creationTime"]
        assert response.partition_mode == "datetime"

    def test_assets_response_has_no_partitioning(self) -> None:
        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="assets",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Dagster Cloud endpoint"):
            dagster_cloud_source("org", "prod", "tok", "nope", MagicMock(), _manager())


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @patch(f"{MODULE}.make_tracked_session")
    def test_auth_failure(self, _name: str, status: int, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        session.post.return_value = response
        mock_session_cls.return_value = session

        ok, error = validate_credentials("org", "prod", "bad")
        assert ok is False
        assert error is not None

    @patch(f"{MODULE}.make_tracked_session")
    def test_success(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"__typename": "Query"}}
        session.post.return_value = response
        mock_session_cls.return_value = session

        assert validate_credentials("org", "prod", "tok") == (True, None)
        # Validation sends the same credentialed header — same redaction/no-redirect posture.
        session_kwargs = mock_session_cls.call_args.kwargs
        assert session_kwargs["redact_values"] == ("tok",)
        assert session_kwargs["allow_redirects"] is False

    @patch(f"{MODULE}.make_tracked_session")
    def test_redirect_fails_validation(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 302
        session.post.return_value = response
        mock_session_cls.return_value = session

        ok, error = validate_credentials("org", "prod", "tok")
        assert ok is False
        assert error is not None and "redirect" in error

    def test_invalid_slug_fails_before_request(self) -> None:
        ok, error = validate_credentials("bad host", "prod", "tok")
        assert ok is False
        assert error is not None


class TestEndpointCatalog:
    def test_incremental_endpoints_are_the_ones_with_server_side_filters(self) -> None:
        # RunsFilter.updatedAfter, InstigationState.ticks(afterTimestamp) and the asset event
        # resolvers' afterTimestampMillis genuinely filter server-side. Every other endpoint would
        # walk full history on an "incremental" run, so it must stay full-refresh.
        incremental = {name for name, cfg in DAGSTER_CLOUD_ENDPOINTS.items() if cfg.supports_incremental}
        assert incremental == {"runs", "instigation_ticks", "asset_materializations", "asset_observations"}

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


def _route(handlers: dict[str, Any]) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    """Mock session.post, dispatching on the posted query's GraphQL operation name.

    A handler is one response reused for every call, or a list consumed in order. Every call is
    recorded so a test can assert what each hop of a fan-out actually sent.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    def side_effect(*_args: object, **kwargs: object) -> MagicMock:
        payload = cast(dict, kwargs["json"])
        match = re.search(r"query (\w+)", payload["query"])
        assert match is not None
        operation = match.group(1)
        variables = payload.get("variables") or {}
        # Copied: the paginators mutate one variables dict in place across a parent's pages.
        calls.append((operation, dict(variables)))

        handler = handlers[operation]
        return handler.pop(0) if isinstance(handler, list) else handler

    return side_effect, calls


def _repositories_response(names: list[tuple[str, str, str]]) -> MagicMock:
    return _gql_response(
        "repositoriesOrError",
        {
            "__typename": "RepositoryConnection",
            "nodes": [
                {"id": repo_id, "name": name, "location": {"name": location}} for repo_id, name, location in names
            ],
        },
    )


def _assets_page(ids: list[str], cursor: str | None) -> MagicMock:
    return _gql_response("assetsOrError", _assets_container(ids, cursor))


def _materializations_response(timestamps_millis: list[str]) -> MagicMock:
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


def _ticks_response(timestamps: list[float]) -> MagicMock:
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
    @patch(f"{MODULE}.make_tracked_session")
    def test_one_child_request_per_repository_with_parent_fields_injected(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                "RepositorySchedules": [
                    _gql_response("schedulesOrError", {"__typename": "Schedules", "results": [{"name": "daily"}]}),
                    _gql_response("schedulesOrError", {"__typename": "Schedules", "results": [{"name": "hourly"}]}),
                ],
            }
        )
        mock_session_cls.return_value = session
        manager = _manager()

        pages = list(_make_fanout_request("org", "prod", "tok", "schedules", MagicMock(), manager))

        rows = [row for page in pages for row in page]
        # Each row has to name its repository: the primary key is only unique with it.
        assert rows == [
            {"name": "daily", "repositoryName": "repo_a", "repositoryLocationName": "loc_a"},
            {"name": "hourly", "repositoryName": "repo_b", "repositoryLocationName": "loc_b"},
        ]
        child_variables = [variables for operation, variables in calls if operation == "RepositorySchedules"]
        assert [v["repositoryName"] for v in child_variables] == ["repo_a", "repo_b"]
        # One parent finished per checkpoint, so a resume restarts at the next repository.
        assert manager.save_state.call_args_list == [
            call(DagsterCloudResumeConfig(parents_done=1)),
            call(DagsterCloudResumeConfig(parents_done=2)),
        ]

    @patch(f"{MODULE}.make_tracked_session")
    def test_repository_deleted_mid_sync_is_skipped(self, mock_session_cls: MagicMock) -> None:
        # The parent list is read before the children, so a repository removed in between must
        # not fail the whole sync.
        session = MagicMock()
        session.post.side_effect, _ = _route(
            {
                "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                "RepositorySensors": [
                    _gql_response("sensorsOrError", {"__typename": "RepositoryNotFoundError", "message": "gone"}),
                    _gql_response("sensorsOrError", {"__typename": "Sensors", "results": [{"name": "s"}]}),
                ],
            }
        )
        mock_session_cls.return_value = session

        pages = list(_make_fanout_request("org", "prod", "tok", "sensors", MagicMock(), _manager()))

        assert [row["name"] for page in pages for row in page] == ["s"]

    @patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_finished_parents(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "Repositories": _repositories_response([("r1", "repo_a", "loc_a"), ("r2", "repo_b", "loc_b")]),
                "RepositorySchedules": _gql_response("schedulesOrError", {"__typename": "Schedules", "results": []}),
            }
        )
        mock_session_cls.return_value = session

        list(
            _make_fanout_request(
                "org",
                "prod",
                "tok",
                "schedules",
                MagicMock(),
                _manager(DagsterCloudResumeConfig(parents_done=1)),
            )
        )

        child_variables = [variables for operation, variables in calls if operation == "RepositorySchedules"]
        assert [v["repositoryName"] for v in child_variables] == ["repo_b"]


class TestTwoLevelFanOut:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_tick_parents_resolve_through_repositories(self, mock_session_cls: MagicMock) -> None:
        # instigation_ticks fans out over instigation states, which themselves only exist per
        # repository — so the walk is repositories -> states -> ticks.
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "Repositories": _repositories_response([("repo-id-1", "repo_a", "loc_a")]),
                "RepositoryInstigationStates": _gql_response(
                    "instigationStatesOrError",
                    {
                        "__typename": "InstigationStates",
                        "results": [
                            {
                                "id": "compound-id",
                                "selectorId": "selector-1",
                                "name": "daily",
                                "instigationType": "SCHEDULE",
                                "repositoryName": "repo_a",
                                "repositoryLocationName": "loc_a",
                            }
                        ],
                    },
                ),
                "InstigationTicks": _ticks_response([1704067200.0]),
            }
        )
        mock_session_cls.return_value = session

        pages = list(_make_fanout_request("org", "prod", "tok", "instigation_ticks", MagicMock(), _manager()))

        state_variables = next(v for op, v in calls if op == "RepositoryInstigationStates")
        assert state_variables == {"repositoryID": "repo-id-1"}
        tick_variables = next(v for op, v in calls if op == "InstigationTicks")
        # The state's compound id disambiguates a schedule and a sensor sharing a name.
        assert tick_variables["instigationStateId"] == "compound-id"
        assert tick_variables["instigationName"] == "daily"

        row = pages[0][0]
        assert row["instigationSelectorId"] == "selector-1"
        # Tick timestamps are epoch-seconds floats, normalized like every other Dagster timestamp.
        assert row["timestamp"] == ISO_2024

    @patch(f"{MODULE}.make_tracked_session")
    def test_incremental_ticks_send_seconds_float_watermark(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, calls = _route(
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
        )
        mock_session_cls.return_value = session

        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="instigation_ticks",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="timestamp",
        )
        list(cast(Iterable[Any], response.items()))

        tick_variables = next(v for op, v in calls if op == "InstigationTicks")
        # ticks(afterTimestamp:) is a Float of epoch seconds, not the asset resolvers' millis string.
        assert tick_variables["afterTimestamp"] == EPOCH_2024


class TestAssetEventFanOut:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_pages_backwards_on_the_oldest_timestamp(self, mock_session_cls: MagicMock) -> None:
        # assetMaterializations has no cursor: the only way to reach older events is to lower
        # beforeTimestampMillis to the oldest timestamp the last page carried.
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "PaginatedAssets": _assets_page(["a1"], cursor=None),
                "AssetMaterializations": [
                    _materializations_response(["1700000002000", "1700000001000"]),
                    _materializations_response(["1700000000000"]),
                ],
            }
        )
        mock_session_cls.return_value = session
        manager = _manager()

        pages = list(_make_fanout_request("org", "prod", "tok", "asset_materializations", MagicMock(), manager))

        event_variables = [v for op, v in calls if op == "AssetMaterializations"]
        assert "beforeTimestampMillis" not in event_variables[0]
        assert event_variables[1]["beforeTimestampMillis"] == "1700000001000"
        assert event_variables[0]["assetKeyPath"] == ["a1"]

        rows = [row for page in pages for row in page]
        assert len(rows) == 3
        assert all(row["assetId"] == "a1" for row in rows)
        # Asset events report epoch milliseconds as a string, unlike runs' epoch-seconds floats.
        assert rows[0]["timestamp"] == "2023-11-14T22:13:22.000000+00:00"
        # Checkpointed mid-parent, then once the parent finished.
        assert manager.save_state.call_args_list == [
            call(DagsterCloudResumeConfig(parents_done=0, window_cursor="1700000001000")),
            call(DagsterCloudResumeConfig(parents_done=1)),
        ]

    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_a_window_that_does_not_advance_fails_the_sync(self, mock_session_cls: MagicMock) -> None:
        # An API that ignored beforeTimestampMillis would replay one page forever. Failing beats
        # truncating: sort_mode is "desc", so a silently short parent still commits a watermark
        # above the events it skipped, and no later sync would ask for them.
        session = MagicMock()
        page = _materializations_response(["1700000001000", "1700000001000"])
        session.post.side_effect, _ = _route(
            {
                "PaginatedAssets": _assets_page(["a1"], cursor=None),
                "AssetMaterializations": [page, page],
            }
        )
        mock_session_cls.return_value = session

        with pytest.raises(Exception, match="page window did not advance"):
            list(_make_fanout_request("org", "prod", "tok", "asset_materializations", MagicMock(), _manager()))

    @patch(f"{MODULE}.make_tracked_session")
    def test_incremental_sends_millis_string_watermark(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "PaginatedAssets": _assets_page(["a1"], cursor=None),
                "AssetMaterializations": _materializations_response([]),
            }
        )
        mock_session_cls.return_value = session

        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="asset_materializations",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="timestamp",
        )
        list(cast(Iterable[Any], response.items()))

        event_variables = next(v for op, v in calls if op == "AssetMaterializations")
        assert event_variables["afterTimestampMillis"] == "1704067200000"

    @patch(f"{MODULE}.make_tracked_session")
    def test_full_refresh_omits_the_watermark(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, calls = _route(
            {
                "PaginatedAssets": _assets_page(["a1"], cursor=None),
                "AssetMaterializations": _materializations_response([]),
            }
        )
        mock_session_cls.return_value = session

        response = dagster_cloud_source(
            organization="org",
            deployment="prod",
            api_token="tok",
            endpoint_name="asset_materializations",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        list(cast(Iterable[Any], response.items()))

        event_variables = next(v for op, v in calls if op == "AssetMaterializations")
        assert "afterTimestampMillis" not in event_variables

    @patch(f"{MODULE}.make_tracked_session")
    def test_asset_deleted_mid_sync_is_skipped(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect, _ = _route(
            {
                "PaginatedAssets": _assets_page(["a1"], cursor=None),
                "AssetObservations": _gql_response(
                    "assetOrError", {"__typename": "AssetNotFoundError", "message": "gone"}
                ),
            }
        )
        mock_session_cls.return_value = session

        pages = list(_make_fanout_request("org", "prod", "tok", "asset_observations", MagicMock(), _manager()))

        assert [row for page in pages for row in page] == []


class TestBatchedFanOut:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch.dict(DAGSTER_CLOUD_ENDPOINTS, {"asset_nodes": _with_batch_size("asset_nodes", 2)})
    @patch(f"{MODULE}.make_tracked_session")
    def test_asset_nodes_batches_keys_and_reads_a_bare_root_list(self, mock_session_cls: MagicMock) -> None:
        # assetNodes returns [AssetNode!]! rather than an OrError union, and takes the keys in
        # one list — so the walk batches parents instead of issuing a request each.
        session = MagicMock()
        node_response = MagicMock()
        node_response.status_code = 200
        node_response.ok = True
        node_response.json.return_value = {
            "data": {"assetNodes": [{"id": "n1", "groupName": "default"}, {"id": "n2", "groupName": "default"}]}
        }
        session.post.side_effect, calls = _route(
            {
                "PaginatedAssets": [_assets_page(["a1", "a2"], cursor="p2"), _assets_page(["a3"], cursor=None)],
                "AssetNodes": [node_response, node_response],
            }
        )
        mock_session_cls.return_value = session
        manager = _manager()

        pages = list(_make_fanout_request("org", "prod", "tok", "asset_nodes", MagicMock(), manager))

        node_variables = [v for op, v in calls if op == "AssetNodes"]
        # Parents are collected up to batch_size, so the first two assets go out together and
        # the trailing one follows in a final partial batch.
        assert node_variables[0]["assetKeys"] == [{"path": ["a1"]}, {"path": ["a2"]}]
        assert node_variables[1]["assetKeys"] == [{"path": ["a3"]}]
        assert len([row for page in pages for row in page]) == 4
        assert manager.save_state.call_args_list == [
            call(DagsterCloudResumeConfig(parents_done=2)),
            call(DagsterCloudResumeConfig(parents_done=3)),
        ]


class TestFanOutRouting:
    def test_unknown_fanout_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Dagster Cloud fan-out endpoint"):
            list(_make_fanout_request("org", "prod", "tok", "runs", MagicMock(), _manager()))


class TestCursorProgress:
    @patch(f"{MODULE}.DAGSTER_CLOUD_PAGE_SIZE", 2)
    @patch(f"{MODULE}.make_tracked_session")
    def test_a_cursor_that_does_not_advance_fails_the_sync(self, mock_session_cls: MagicMock) -> None:
        # Nothing else bounds the cursor walk, so a repeated cursor would re-request one page
        # until the activity timed out.
        session = MagicMock()
        session.post.return_value = _gql_response("runsOrError", _runs_container(["r1", "r1"]))
        mock_session_cls.return_value = session

        with pytest.raises(Exception, match="pagination cursor did not advance"):
            list(_make_paginated_request("org", "prod", "tok", "runs", MagicMock(), _manager()))
