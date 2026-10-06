from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from grpclib import GRPCError, Status
from modal.exception import AuthError, PermissionDeniedError, ResourceExhaustedError, ServiceError
from modal.types import BillingReportItem

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.modal import ModalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.modal import (
    ModalAuthenticationError,
    ModalPermissionError,
    ModalResumeConfig,
    modal_source,
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


@pytest.mark.parametrize("tz", [None, UTC, timezone(timedelta(hours=5, minutes=30))])
@pytest.mark.parametrize("cost", ["0", "1.23456789", "-0.125"])
def test_rows_are_sorted_and_normalized(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
    tz: timezone | None,
    cost: str,
) -> None:
    early = datetime(2026, 3, 14, tzinfo=tz)
    late = early + timedelta(hours=1)
    original = [billing_item(late, cost), billing_item(early, cost)]
    report.return_value = original
    response = modal_source(config, inputs, manager)
    (rows,) = list(source_items(response))
    expected_early = early.replace(tzinfo=UTC) if tz is None else early.astimezone(UTC)
    assert [row["interval_start"] for row in rows] == [expected_early, expected_early + timedelta(hours=1)]
    assert rows[0] == {
        "object_id": "ap-test",
        "description": "Example app",
        "environment_name": "main",
        "interval_start": expected_early,
        "cost": float(Decimal(cost)),
        "tags": {"team": "example", "project": "billing-test"},
    }
    assert isinstance(rows[0]["cost"], float)
    assert rows[0]["tags"] is not original[1].tags
    assert original[0].cost == Decimal(cost)
    manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    ("object_id", "description", "environment_name", "cost", "cost_by_resource", "tags"),
    [
        ("ap-first", "First app", "main", "1.23456789", {"cpu": Decimal("1.23456789")}, {"team": "example"}),
        ("ap-second", "Second app", "staging", "0", {}, {}),
    ],
)
def test_report_item_conversion(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    report: MagicMock,
    object_id: str,
    description: str,
    environment_name: str,
    cost: str,
    cost_by_resource: dict[str, Decimal],
    tags: dict[str, str],
) -> None:
    interval_start = datetime(2026, 3, 14, tzinfo=UTC)
    item = BillingReportItem(
        object_id=object_id,
        description=description,
        environment_name=environment_name,
        interval_start=interval_start,
        cost=Decimal(cost),
        cost_by_resource=cost_by_resource,
        tags=tags,
    )
    report.return_value = [item]

    (rows,) = list(source_items(modal_source(config, inputs, manager)))

    assert rows == [
        {
            "object_id": object_id,
            "description": description,
            "environment_name": environment_name,
            "interval_start": interval_start,
            "cost": float(Decimal(cost)),
            "tags": tags,
        }
    ]
    assert rows[0]["tags"] is not item.tags


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


@pytest.mark.parametrize("state", [None, ModalResumeConfig(next_window_start=NOW.isoformat(), end=NOW.isoformat())])
def test_resume_without_work(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    create_client: MagicMock,
    report: MagicMock,
    state: ModalResumeConfig | None,
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = state
    list(source_items(modal_source(config, inputs, manager)))
    assert report.call_count == (1 if state is None else 0)


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
