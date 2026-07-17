from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud import (
    DagsterCloudResumeConfig,
    _build_runs_filter,
    _epoch_to_iso,
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

    def test_invalid_slug_fails_before_request(self) -> None:
        ok, error = validate_credentials("bad host", "prod", "tok")
        assert ok is False
        assert error is not None


class TestEndpointCatalog:
    def test_only_runs_is_incremental(self) -> None:
        # Backfills/assets have no server-side timestamp filter, so they must stay full-refresh.
        incremental = {name for name, cfg in DAGSTER_CLOUD_ENDPOINTS.items() if cfg.supports_incremental}
        assert incremental == {"runs"}
