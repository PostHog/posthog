from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import modal
from grpclib import GRPCError, Status
from modal.client import _Client
from modal.exception import AuthError, NotFoundError, PermissionDeniedError, ResourceExhaustedError, ServiceError
from modal.types import BillingReportItem, WorkspaceBillingSummary
from modal_proto import api_pb2

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.modal import ModalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.modal import (
    MAX_REPORT_RETRY_ATTEMPTS,
    ModalAuthenticationError,
    ModalPermissionError,
    ModalResumeConfig,
    modal_source,
    strip_url_credentials,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.source import ModalSource

NOW = datetime(2026, 3, 15, 12, 34, 56, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def config() -> ModalSourceConfig:
    return ModalSourceConfig.from_dict({"token_id": "ak-test", "token_secret": "as-test-secret"})


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="billing_report_daily",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-03-14T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="interval_start",
        incremental_field_type=None,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def create_client() -> Iterator[MagicMock]:
    with patch("modal.Client.from_credentials") as create:
        yield create


@pytest.fixture
def workspace() -> Iterator[MagicMock]:
    with patch("modal.Workspace.from_context") as from_context:
        yield from_context


@pytest.fixture
def report(workspace: MagicMock) -> MagicMock:
    report = workspace.return_value.billing.report
    report.return_value = []
    return report


def source_items(response: SourceResponse) -> Iterable[list[dict[str, object]]]:
    return cast(Iterable[list[dict[str, object]]], response.items())


def billing_item(interval_start: datetime, cost: str = "1.23456789") -> BillingReportItem:
    return BillingReportItem(
        object_id="ap-test",
        description="Example app",
        environment_name="main",
        interval_start=interval_start,
        cost=Decimal(cost),
        cost_by_resource={"cpu": Decimal(cost)},
        tags={"team": "example", "project": "billing-test"},
    )


@pytest.mark.parametrize(
    ("table", "watermark", "incremental", "expected_start", "window_days", "resolution"),
    [
        ("daily", "2026-01-01T18:45:00Z", True, datetime(2026, 1, 1, tzinfo=UTC), 30, "d"),
        ("hourly", "2026-03-10T18:45:00Z", True, datetime(2026, 3, 10, 18, tzinfo=UTC), 2, "h"),
        ("daily", None, True, datetime(2025, 3, 15, tzinfo=UTC), 30, "d"),
        ("hourly", None, True, datetime(2026, 2, 13, 12, tzinfo=UTC), 2, "h"),
        ("daily", "2026-03-14T00:00:00Z", False, datetime(2025, 3, 15, tzinfo=UTC), 30, "d"),
        ("hourly", "2026-03-14T00:00:00Z", False, datetime(2026, 2, 13, 12, tzinfo=UTC), 2, "h"),
        ("hourly", "2026-03-15T11:25:00-02:00", True, datetime(2026, 3, 15, 13, tzinfo=UTC), 2, "h"),
        ("daily", "2026-03-16T00:00:00Z", True, datetime(2026, 3, 16, tzinfo=UTC), 30, "d"),
        ("hourly", datetime(2026, 3, 14, 18, 30), True, datetime(2026, 3, 14, 18, tzinfo=UTC), 2, "h"),
    ],
)
def test_forward_windows(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    workspace: MagicMock,
    report: MagicMock,
    table: str,
    watermark: datetime | str | None,
    incremental: bool,
    expected_start: datetime,
    window_days: int,
    resolution: str,
) -> None:
    inputs.schema_name = f"billing_report_{table}"
    inputs.db_incremental_field_last_value = watermark
    inputs.should_use_incremental_field = incremental
    assert list(source_items(modal_source(config, inputs, manager))) == []

    if expected_start >= NOW:
        report.assert_not_called()
        create_client.assert_not_called()
        workspace.assert_not_called()
        return

    calls = [call.kwargs for call in report.call_args_list]
    assert calls[0]["start"] == expected_start
    assert calls[-1]["end"] == NOW
    for index, request in enumerate(calls):
        assert request["start"] < request["end"] <= NOW
        assert request["end"] - request["start"] <= timedelta(days=window_days)
        assert request["resolution"] == resolution
        assert request["tag_names"] == ["*"]
        if index:
            assert request["start"] == calls[index - 1]["end"]
    assert manager.safe_point.call_count == len(calls)
    assert [call.args[0].next_window_start for call in manager.save_state.call_args_list] == [
        request["end"].isoformat() for request in calls
    ]
    create_client.assert_called_once_with("ak-test", "as-test-secret")
    workspace.assert_called_once_with(client=create_client.return_value)
    create_client.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("has_rows", [True, False])
def test_retry_resumes_after_saved_window(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
    has_rows: bool,
) -> None:
    inputs.schema_name = "billing_report_hourly"
    inputs.db_incremental_field_last_value = "2026-03-10T00:00:00Z"
    rows = [billing_item(datetime(2026, 3, 10, tzinfo=UTC))] if has_rows else []
    report.side_effect = [rows, ServiceError("temporary failure")]
    iterator = iter(source_items(modal_source(config, inputs, manager)))
    if has_rows:
        assert next(iterator)
        manager.save_state.assert_called_once()
    with pytest.raises(ServiceError, match="temporary failure"):
        list(iterator)
    saved = manager.save_state.call_args.args[0]
    assert saved == ModalResumeConfig(next_window_start="2026-03-12T00:00:00+00:00", end=NOW.isoformat())
    create_client.return_value.__exit__.assert_called_once()
    manager.clear_state.assert_not_called()

    manager.can_resume.return_value = True
    manager.load_state.return_value = saved
    report.reset_mock()
    report.side_effect = None
    report.return_value = []
    with time_machine.travel(NOW + timedelta(days=1), tick=False):
        assert list(source_items(modal_source(config, inputs, manager))) == []
    assert report.call_args_list[0].kwargs["start"] == datetime(2026, 3, 12, tzinfo=UTC)
    assert report.call_args_list[-1].kwargs["end"] == NOW


def test_rides_out_rate_limit_on_report(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
) -> None:
    inputs.schema_name = "billing_report_hourly"
    inputs.db_incremental_field_last_value = "2026-03-15T10:00:00Z"
    rows = [billing_item(datetime(2026, 3, 15, 10, tzinfo=UTC))]
    report.side_effect = [ResourceExhaustedError("rate limit"), ResourceExhaustedError("rate limit"), rows]

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.modal.modal.interruptible_wait",
        return_value=False,
    ) as wait:
        result = list(source_items(modal_source(config, inputs, manager)))

    # Two rate-limit rejections were retried in-process, then the same window was served — no data lost.
    assert report.call_count == 3
    assert [item["object_id"] for item in result[0]] == ["ap-test"]
    # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st rejection, 4s after the 2nd.
    assert [c.args for c in wait.call_args_list] == [(2,), (4,)]
    create_client.return_value.__exit__.assert_called_once()


def test_persistent_rate_limit_is_reraised_for_temporal_to_retry(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
) -> None:
    inputs.schema_name = "billing_report_hourly"
    inputs.db_incremental_field_last_value = "2026-03-15T10:00:00Z"
    report.side_effect = ResourceExhaustedError("rate limit")

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.modal.modal.interruptible_wait",
        return_value=False,
    ) as wait:
        with pytest.raises(ResourceExhaustedError, match="rate limit"):
            list(source_items(modal_source(config, inputs, manager)))

    assert report.call_count == MAX_REPORT_RETRY_ATTEMPTS
    assert [c.args for c in wait.call_args_list] == [(2,), (4,), (6,)]
    manager.save_state.assert_not_called()
    create_client.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("during_creation", [False, True])
@pytest.mark.parametrize(
    ("error", "mapped_type", "message"),
    [
        (
            AuthError("invalid token"),
            ModalAuthenticationError,
            "Modal authentication failed. Check your token ID and token secret.",
        ),
        (
            PermissionDeniedError("denied"),
            ModalPermissionError,
            "Modal billing access was denied. Use a Team or Enterprise plan with a token that can read workspace billing.",
        ),
        (
            GRPCError(Status.UNAUTHENTICATED, "invalid token"),
            ModalAuthenticationError,
            "Modal authentication failed. Check your token ID and token secret.",
        ),
        (
            GRPCError(Status.PERMISSION_DENIED, "denied"),
            ModalPermissionError,
            "Modal billing access was denied. Use a Team or Enterprise plan with a token that can read workspace billing.",
        ),
    ],
)
def test_auth_and_permission_errors(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
    during_creation: bool,
    error: Exception,
    mapped_type: type[Exception],
    message: str,
) -> None:
    (create_client if during_creation else report).side_effect = error
    assert validate_credentials(config) == (False, message)
    with pytest.raises(mapped_type) as raised:
        list(source_items(modal_source(config, inputs, manager)))
    assert str(raised.value) == message
    assert any(pattern in str(raised.value) for pattern in ModalSource().get_non_retryable_errors())
    assert create_client.return_value.__exit__.call_count == (0 if during_creation else 2)
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [ServiceError("unavailable"), ResourceExhaustedError("rate limit"), GRPCError(Status.UNAVAILABLE, "unavailable")],
)
def test_transient_errors_propagate(
    config: ModalSourceConfig,
    create_client: MagicMock,
    report: MagicMock,
    error: Exception,
) -> None:
    report.side_effect = error
    with pytest.raises(type(error)) as raised:
        validate_credentials(config)
    assert raised.value is error
    assert not any(pattern in str(error) for pattern in ModalSource().get_non_retryable_errors())
    create_client.return_value.__exit__.assert_called_once()


def test_credential_probe_uses_one_complete_day(
    config: ModalSourceConfig, create_client: MagicMock, workspace: MagicMock, report: MagicMock
) -> None:
    assert validate_credentials(config) == (True, None)
    report.assert_called_once_with(
        start=datetime(2026, 3, 14, tzinfo=UTC),
        end=datetime(2026, 3, 15, tzinfo=UTC),
        resolution="d",
        tag_names=["*"],
    )
    workspace.assert_called_once_with(client=create_client.return_value)
    create_client.return_value.__exit__.assert_called_once()


def test_unknown_table_does_not_connect(
    config: ModalSourceConfig, inputs: SourceInputs, manager: MagicMock, create_client: MagicMock, report: MagicMock
) -> None:
    inputs.schema_name = "unknown"
    with pytest.raises(UnknownResourceError):
        modal_source(config, inputs, manager)
    create_client.assert_not_called()
    report.assert_not_called()


def billing_summary(cycle: datetime) -> WorkspaceBillingSummary:
    return WorkspaceBillingSummary(
        start=cycle,
        end=cycle + timedelta(days=28),
        metered_cost=Decimal("120.50"),
        metered_cost_breakdown={"cpu": Decimal("100.25"), "gpu": Decimal("20.25")},
        adjustments={"credits": Decimal("-30")},
        billed_cost=Decimal("90.50"),
    )


@pytest.mark.parametrize(
    ("watermark", "incremental", "resume", "expected_cycles"),
    [
        (
            None,
            True,
            None,
            [datetime(2025, month, 1, tzinfo=UTC) for month in range(4, 13)]
            + [datetime(2026, month, 1, tzinfo=UTC) for month in range(1, 4)],
        ),
        ("2026-01-14T00:00:00Z", True, None, [datetime(2026, month, 1, tzinfo=UTC) for month in range(1, 4)]),
        ("2025-12-31T23:00:00-02:00", True, None, [datetime(2026, month, 1, tzinfo=UTC) for month in range(1, 4)]),
        ("2026-03-01T00:00:00Z", True, None, [datetime(2026, 3, 1, tzinfo=UTC)]),
        (
            "2026-03-01T00:00:00Z",
            False,
            None,
            [datetime(2025, month, 1, tzinfo=UTC) for month in range(4, 13)]
            + [datetime(2026, month, 1, tzinfo=UTC) for month in range(1, 4)],
        ),
        ("2026-04-01T00:00:00Z", True, None, []),
        (
            None,
            True,
            ModalResumeConfig(next_window_start="2025-12-01T00:00:00+00:00", end="2026-01-01T00:00:00+00:00"),
            [datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)],
        ),
    ],
)
def test_billing_summary_cycles(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    workspace: MagicMock,
    watermark: str | None,
    incremental: bool,
    resume: ModalResumeConfig | None,
    expected_cycles: list[datetime],
) -> None:
    inputs.schema_name = "billing_summary"
    inputs.db_incremental_field_last_value = watermark
    inputs.should_use_incremental_field = incremental
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    summary = workspace.return_value.billing.summary
    summary.side_effect = lambda cycle: billing_summary(cycle)

    batches = list(source_items(modal_source(config, inputs, manager)))

    assert [call.kwargs["cycle"] for call in summary.call_args_list] == expected_cycles
    assert [row["cycle_start"] for batch in batches for row in batch] == expected_cycles
    assert all(len(batch) == 1 for batch in batches)
    assert [call.args[0].next_window_start for call in manager.save_state.call_args_list] == [
        (datetime(cycle.year + cycle.month // 12, cycle.month % 12 + 1, 1, tzinfo=UTC)).isoformat()
        for cycle in expected_cycles
    ]
    if not expected_cycles:
        create_client.assert_not_called()
        return
    assert batches[0][0] == {
        "cycle_start": expected_cycles[0],
        "cycle_end": expected_cycles[0] + timedelta(days=28),
        "metered_cost": 120.5,
        "billed_cost": 90.5,
        "metered_cost_breakdown": {"cpu": 100.25, "gpu": 20.25},
        "adjustments": {"credits": -30.0},
    }
    create_client.return_value.__exit__.assert_called_once()


def app_item(
    app_id: str, state: api_pb2.AppState.ValueType = api_pb2.APP_STATE_DEPLOYED
) -> api_pb2.AppListResponse.AppListItem:
    return api_pb2.AppListResponse.AppListItem(
        app_id=app_id,
        name=f"name-{app_id}",
        description=f"Example {app_id}",
        state=state,
        created_at=NOW.timestamp() - 86400,
        n_running_tasks=2,
    )


def sandbox_info(sandbox_id: str, created_at: float, finished: bool = True) -> api_pb2.SandboxInfo:
    return api_pb2.SandboxInfo(
        id=sandbox_id,
        app_id="ap-one",
        created_at=created_at,
        task_info=api_pb2.TaskInfo(
            id="ta-test",
            started_at=created_at + 5,
            finished_at=created_at + 60 if finished else 0,
            result=api_pb2.GenericResult(status=api_pb2.GenericResult.GENERIC_STATUS_TIMEOUT, exitcode=137)
            if finished
            else None,
        ),
        resource_info=api_pb2.ResourceInfo(
            milli_cpu=api_pb2.ResourceInfo.ResourceValue(value=500),
            memory_mb=api_pb2.ResourceInfo.ResourceValue(value=1024),
        ),
        tags=[api_pb2.SandboxTag(tag_name="team", tag_value="example")],
        regions=["us-east"],
        timeout_secs=300,
    )


@pytest.fixture
def stub() -> Iterator[MagicMock]:
    stub = MagicMock()
    stub.EnvironmentList = AsyncMock(
        return_value=api_pb2.EnvironmentListResponse(
            items=[api_pb2.EnvironmentListItem(name="main"), api_pb2.EnvironmentListItem(name="dev")]
        )
    )
    with patch.object(_Client, "stub", new_callable=PropertyMock, return_value=stub):
        yield stub


@pytest.fixture
def real_client(create_client: MagicMock) -> modal.Client:
    client = modal.Client("https://api.modal.com", api_pb2.CLIENT_TYPE_CLIENT, ("ak-test", "as-test-secret"))
    create_client.return_value = client
    return client


def test_apps_list_every_environment(
    config: ModalSourceConfig, inputs: SourceInputs, manager: MagicMock, real_client: modal.Client, stub: MagicMock
) -> None:
    inputs.schema_name = "apps"
    apps = {"main": [app_item("ap-one"), app_item("ap-two", state=api_pb2.AppState.ValueType(99))], "dev": []}
    stub.AppList = AsyncMock(side_effect=lambda request: api_pb2.AppListResponse(apps=apps[request.environment_name]))

    batches = list(source_items(modal_source(config, inputs, manager)))

    assert [call.args[0].environment_name for call in stub.AppList.call_args_list] == ["main", "dev"]
    assert batches == [
        [
            {
                "app_id": "ap-one",
                "name": "name-ap-one",
                "description": "Example ap-one",
                "state": "deployed",
                "environment_name": "main",
                "created_at": NOW - timedelta(days=1),
                "stopped_at": None,
                "n_running_tasks": 2,
            },
            {
                "app_id": "ap-two",
                "name": "name-ap-two",
                "description": "Example ap-two",
                "state": "99",
                "environment_name": "main",
                "created_at": NOW - timedelta(days=1),
                "stopped_at": None,
                "n_running_tasks": 2,
            },
        ]
    ]
    assert manager.safe_point.call_count == 2


@pytest.mark.parametrize(
    ("pages", "expected_cursors", "expected_ids"),
    [
        ([[]], [0.0], []),
        (
            [
                [sandbox_info("sb-3", 3000.0), sandbox_info("sb-2", 2000.0)],
                [sandbox_info("sb-1", 1000.0)],
                [],
            ],
            [0.0, 2000.0, 1000.0],
            ["sb-3", "sb-2", "sb-1"],
        ),
        (
            [[sandbox_info("sb-2", 2000.0)], [sandbox_info("sb-2", 2000.0)]],
            [0.0, 2000.0],
            ["sb-2", "sb-2"],
        ),
    ],
)
def test_sandboxes_page_back_through_each_app(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    real_client: modal.Client,
    stub: MagicMock,
    pages: list[list[api_pb2.SandboxInfo]],
    expected_cursors: list[float],
    expected_ids: list[str],
) -> None:
    inputs.schema_name = "sandboxes"
    stub.AppList = AsyncMock(
        side_effect=lambda request: api_pb2.AppListResponse(
            apps=[app_item("ap-one")] if request.environment_name == "main" else []
        )
    )
    responses = iter(pages)
    stub.SandboxList = AsyncMock(side_effect=lambda request: api_pb2.SandboxListResponse(sandboxes=next(responses)))

    rows = [row for batch in source_items(modal_source(config, inputs, manager)) for row in batch]

    requests = [call.args[0] for call in stub.SandboxList.call_args_list]
    assert [request.before_timestamp for request in requests] == expected_cursors
    assert all(request.app_id == "ap-one" and request.environment_name == "main" for request in requests)
    assert all(request.include_finished for request in requests)
    assert [row["id"] for row in rows] == expected_ids
    assert manager.safe_point.call_count == len(pages)


@pytest.mark.parametrize("finished", [True, False])
def test_sandbox_row_shape(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    real_client: modal.Client,
    stub: MagicMock,
    finished: bool,
) -> None:
    inputs.schema_name = "sandboxes"
    created_at = NOW.timestamp() - 3600
    stub.AppList = AsyncMock(
        side_effect=lambda request: api_pb2.AppListResponse(
            apps=[app_item("ap-one")] if request.environment_name == "main" else []
        )
    )
    stub.SandboxList = AsyncMock(
        side_effect=[
            api_pb2.SandboxListResponse(sandboxes=[sandbox_info("sb-1", created_at, finished=finished)]),
            api_pb2.SandboxListResponse(),
        ]
    )

    (batch,) = list(source_items(modal_source(config, inputs, manager)))

    assert batch == [
        {
            "id": "sb-1",
            "name": None,
            "app_id": "ap-one",
            "environment_name": "main",
            "image_id": None,
            "created_at": NOW - timedelta(hours=1),
            "ready_at": None,
            "task_id": "ta-test",
            "enqueued_at": None,
            "started_at": NOW - timedelta(hours=1) + timedelta(seconds=5),
            "finished_at": NOW - timedelta(hours=1) + timedelta(seconds=60) if finished else None,
            "status": "timeout" if finished else None,
            "exit_code": 137 if finished else None,
            "gpu_type": None,
            "milli_cpu": 500,
            "milli_cpu_max": None,
            "memory_mb": 1024,
            "memory_mb_max": None,
            "ephemeral_disk_mb": None,
            "regions": ["us-east"],
            "timeout_secs": 300,
            "idle_timeout_secs": None,
            "tags": {"team": "example"},
        }
    ]


def test_app_deployments_skip_undeployed_and_deleted_apps(
    config: ModalSourceConfig, inputs: SourceInputs, manager: MagicMock, real_client: modal.Client, stub: MagicMock
) -> None:
    inputs.schema_name = "app_deployments"
    apps = {
        "main": [
            app_item("ap-deployed"),
            app_item("ap-ephemeral", state=api_pb2.APP_STATE_EPHEMERAL),
            app_item("ap-deleted", state=api_pb2.APP_STATE_STOPPED),
        ],
        "dev": [],
    }
    stub.AppList = AsyncMock(side_effect=lambda request: api_pb2.AppListResponse(apps=apps[request.environment_name]))
    deployed_at = NOW.timestamp() - 3600
    histories = {
        "ap-deployed": api_pb2.AppDeploymentHistoryResponse(
            app_deployment_histories=[
                api_pb2.AppDeploymentHistory(
                    app_id="ap-deployed",
                    version=2,
                    deployed_at=deployed_at,
                    deployed_by="example-user",
                    client_version="1.5.4",
                    deployment_type=api_pb2.DEPLOYMENT_TYPE_ROLLBACK,
                    rollback_version=1,
                ),
                api_pb2.AppDeploymentHistory(
                    app_id="ap-deployed",
                    version=1,
                    deployed_at=deployed_at - 60,
                    deployed_by="example-user",
                    deployment_type=api_pb2.DeploymentType.ValueType(99),
                    commit_info=api_pb2.CommitInfo(
                        vcs="git",
                        branch="main",
                        commit_hash="abc123",
                        commit_timestamp=int(deployed_at) - 120,
                        dirty=True,
                    ),
                ),
            ],
            production_app_version=2,
        ),
    }

    def deployment_history(request: api_pb2.AppDeploymentHistoryRequest) -> api_pb2.AppDeploymentHistoryResponse:
        if request.app_id not in histories:
            raise NotFoundError("App not found")
        return histories[request.app_id]

    stub.AppDeploymentHistory = AsyncMock(side_effect=deployment_history)

    batches = list(source_items(modal_source(config, inputs, manager)))

    assert [call.args[0].app_id for call in stub.AppDeploymentHistory.call_args_list] == ["ap-deployed", "ap-deleted"]
    common = {
        "app_id": "ap-deployed",
        "app_name": "name-ap-deployed",
        "environment_name": "main",
        "deployed_by": "example-user",
        "tag": None,
        "rollback_allowed": False,
        "commit_repo_url": None,
        "commit_author_name": None,
    }
    assert batches == [
        [
            {
                **common,
                "version": 2,
                "is_production": True,
                "deployed_at": NOW - timedelta(hours=1),
                "client_version": "1.5.4",
                "deployment_type": "rollback",
                "rollback_version": 1,
                "commit_hash": None,
                "commit_branch": None,
                "commit_dirty": None,
                "committed_at": None,
            },
            {
                **common,
                "version": 1,
                "is_production": False,
                "deployed_at": NOW - timedelta(hours=1, minutes=1),
                "client_version": None,
                "deployment_type": "99",
                "rollback_version": None,
                "commit_hash": "abc123",
                "commit_branch": "main",
                "commit_dirty": True,
                "committed_at": NOW - timedelta(hours=1, minutes=2),
            },
        ]
    ]
    assert manager.safe_point.call_count == 2


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x-access-token:fake-token@github.com/example/repo.git", "https://github.com/example/repo.git"),
        ("https://fake-token@gitlab.example.com:8443/example/repo", "https://gitlab.example.com:8443/example/repo"),
        ("https://github.com/example/repo.git", "https://github.com/example/repo.git"),
        ("git@github.com:example/repo.git", "git@github.com:example/repo.git"),
        ("", ""),
    ],
)
def test_strip_url_credentials(url: str, expected: str) -> None:
    assert strip_url_credentials(url) == expected


def test_workspace_members(
    config: ModalSourceConfig, inputs: SourceInputs, manager: MagicMock, real_client: modal.Client, stub: MagicMock
) -> None:
    inputs.schema_name = "workspace_members"
    joined_at = NOW.timestamp() - 86400
    stub.WorkspaceMembersList = AsyncMock(
        return_value=api_pb2.WorkspaceMembersListResponse(
            members=[
                api_pb2.WorkspaceMembersListItem(
                    user_id="us-one",
                    member_displayname="example-owner",
                    email="owner@example.com",
                    member_role=api_pb2.MEMBER_ROLE_OWNER,
                    identity_provider_type=api_pb2.IDENTITY_PROVIDER_TYPE_GITHUB,
                    joined_at=joined_at,
                    last_active_at=joined_at + 60,
                ),
                api_pb2.WorkspaceMembersListItem(
                    user_id="us-two", member_role=api_pb2.MemberRole.ValueType(99), joined_at=joined_at
                ),
            ]
        )
    )

    batches = list(source_items(modal_source(config, inputs, manager)))

    assert batches == [
        [
            {
                "user_id": "us-one",
                "name": "example-owner",
                "email": "owner@example.com",
                "role": "owner",
                "identity_provider": "github",
                "joined_at": NOW - timedelta(days=1),
                "last_active_at": NOW - timedelta(days=1) + timedelta(minutes=1),
                "deleted_at": None,
            },
            {
                "user_id": "us-two",
                "name": None,
                "email": None,
                "role": "99",
                "identity_provider": "unspecified",
                "joined_at": NOW - timedelta(days=1),
                "last_active_at": None,
                "deleted_at": None,
            },
        ]
    ]
