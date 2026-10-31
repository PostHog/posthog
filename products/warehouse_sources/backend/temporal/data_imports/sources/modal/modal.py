from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import modal
from google.protobuf.descriptor import EnumDescriptor
from google.protobuf.empty_pb2 import Empty
from grpclib import GRPCError, Status
from modal._utils.async_utils import synchronizer
from modal.client import _Client
from modal.environments import list_environments
from modal.exception import AuthError, NotFoundError, PermissionDeniedError, ResourceExhaustedError
from modal.types import BillingReportItem
from modal_proto import api_pb2

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.settings import (
    APP_DEPLOYMENTS,
    APPS,
    BILLING_REPORT_PARTITION_KEY,
    BILLING_REPORT_PRIMARY_KEYS,
    BILLING_REPORT_TABLES,
    BILLING_SUMMARY,
    BILLING_SUMMARY_DEFAULT_CYCLES,
    SANDBOXES,
    WORKSPACE_MEMBERS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.modal import (
        ModalSourceConfig,
    )


AUTH_ERROR = "Modal authentication failed. Check your token ID and token secret."
PERMISSION_ERROR = (
    "Modal billing access was denied. Use a Team or Enterprise plan with a token that can read workspace billing."
)


class ModalAuthenticationError(Exception):
    pass


class ModalPermissionError(Exception):
    pass


@frozen
class ModalResumeConfig:
    next_window_start: str
    end: str


def as_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    return value.replace(year=index // 12, month=index % 12 + 1)


def from_epoch(value: float) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


def enum_label(descriptor: EnumDescriptor, value: int, prefix: str) -> str:
    member = descriptor.values_by_number.get(value)
    # The server can send enum values that the pinned SDK does not know yet.
    return member.name.removeprefix(prefix).lower() if member else str(value)


# The SDK has no public call for these RPCs, so this uses the same blocking wrapper as the Modal CLI.
async def _list_apps(client: _Client, environment_name: str) -> list[api_pb2.AppListResponse.AppListItem]:
    response = await client.stub.AppList(api_pb2.AppListRequest(environment_name=environment_name))
    return list(response.apps)


async def _list_sandbox_page(
    client: _Client, app_id: str, environment_name: str, before_timestamp: float
) -> list[api_pb2.SandboxInfo]:
    request = api_pb2.SandboxListRequest(
        app_id=app_id,
        environment_name=environment_name,
        before_timestamp=before_timestamp,
        include_finished=True,
    )
    response = await client.stub.SandboxList(request)
    return list(response.sandboxes)


async def _get_deployment_history(client: _Client, app_id: str) -> api_pb2.AppDeploymentHistoryResponse:
    return await client.stub.AppDeploymentHistory(api_pb2.AppDeploymentHistoryRequest(app_id=app_id))


async def _list_workspace_members(client: _Client) -> list[api_pb2.WorkspaceMembersListItem]:
    response = await client.stub.WorkspaceMembersList(Empty())
    return list(response.members)


_list_apps_blocking = synchronizer.create_blocking(_list_apps)
_list_sandbox_page_blocking = synchronizer.create_blocking(_list_sandbox_page)
_get_deployment_history_blocking = synchronizer.create_blocking(_get_deployment_history)
_list_workspace_members_blocking = synchronizer.create_blocking(_list_workspace_members)


def list_apps(client: modal.Client, environment_name: str) -> list[api_pb2.AppListResponse.AppListItem]:
    return _list_apps_blocking(client, environment_name)


def list_sandbox_page(
    client: modal.Client, app_id: str, environment_name: str, before_timestamp: float
) -> list[api_pb2.SandboxInfo]:
    return _list_sandbox_page_blocking(client, app_id, environment_name, before_timestamp)


def get_deployment_history(client: modal.Client, app_id: str) -> api_pb2.AppDeploymentHistoryResponse:
    return _get_deployment_history_blocking(client, app_id)


def list_workspace_members(client: modal.Client) -> list[api_pb2.WorkspaceMembersListItem]:
    return _list_workspace_members_blocking(client)


@contextmanager
def billing_client(config: ModalSourceConfig) -> Iterator[modal.Client]:
    try:
        client = modal.Client.from_credentials(config.token_id, config.token_secret)
        try:
            yield client
        finally:
            # from_credentials opens the client, so entering it again would open it twice.
            client.__exit__(None, None, None)
    except AuthError:
        raise ModalAuthenticationError(AUTH_ERROR) from None
    except PermissionDeniedError:
        raise ModalPermissionError(PERMISSION_ERROR) from None
    except modal.Error:
        raise
    except GRPCError as error:
        if error.status == Status.UNAUTHENTICATED:
            raise ModalAuthenticationError(AUTH_ERROR) from None
        if error.status == Status.PERMISSION_DENIED:
            raise ModalPermissionError(PERMISSION_ERROR) from None
        raise


def validate_credentials(config: ModalSourceConfig) -> tuple[bool, str | None]:
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with billing_client(config) as client:
            modal.Workspace.from_context(client=client).billing.report(
                start=end - timedelta(days=1), end=end, resolution="d", tag_names=["*"]
            )
    except (ModalAuthenticationError, ModalPermissionError) as error:
        return False, str(error)
    return True, None


# Modal's own gRPC client already retries DEADLINE_EXCEEDED/UNAVAILABLE/CANCELLED/INTERNAL/UNKNOWN
# transport errors (see modal._utils.grpc_utils.RETRYABLE_GRPC_STATUS_CODES), but deliberately
# excludes RESOURCE_EXHAUSTED, so a workspace-level rate limit on the billing-report RPC reaches us
# directly as ResourceExhaustedError. Riding it out here with a short backoff avoids failing the
# whole import activity, which would otherwise rebuild the gRPC client and resume from the last
# saved window anyway.
MAX_REPORT_RETRY_ATTEMPTS = 4
MAX_REPORT_BACKOFF_SECONDS = 30


def _report_with_rate_limit_retry(
    workspace: "modal.Workspace",
    *,
    start: datetime,
    end: datetime,
    resolution: str,
    tag_names: list[str],
    safe_point: Callable[[], None],
) -> list[BillingReportItem]:
    attempt = 0
    while True:
        try:
            return workspace.billing.report(start=start, end=end, resolution=resolution, tag_names=tag_names)
        except ResourceExhaustedError:
            attempt += 1
            if attempt >= MAX_REPORT_RETRY_ATTEMPTS:
                raise
            # Every row before this window is already yielded and its cursor staged, so a worker
            # shutdown during the backoff can hand the run off from here without losing rows.
            if interruptible_wait(min(2 * attempt, MAX_REPORT_BACKOFF_SECONDS), safe_point=safe_point):
                raise


def modal_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    if inputs.schema_name == BILLING_SUMMARY:
        return billing_summary_source(config, inputs, resumable_source_manager)
    if inputs.schema_name == APPS:
        return apps_source(config, inputs, resumable_source_manager)
    if inputs.schema_name == SANDBOXES:
        return sandboxes_source(config, inputs, resumable_source_manager)
    if inputs.schema_name == APP_DEPLOYMENTS:
        return app_deployments_source(config, inputs, resumable_source_manager)
    if inputs.schema_name == WORKSPACE_MEMBERS:
        return workspace_members_source(config, inputs)
    return billing_report_source(config, inputs, resumable_source_manager)


def billing_report_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    table = schema_for_resource(BILLING_REPORT_TABLES, inputs.schema_name)

    def get_rows() -> Iterator[list[dict[str, object]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        end = as_utc(resume.end) if resume else datetime.now(UTC)
        if resume:
            start = as_utc(resume.next_window_start)
        else:
            watermark = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            start = as_utc(watermark) if watermark is not None else end - table.default_lookback
            # Re-read the watermark interval because its cost can change after the previous sync.
            start = start.replace(minute=0, second=0, microsecond=0)
            if table.resolution == "d":
                start = start.replace(hour=0)

        if start >= end:
            return

        with billing_client(config) as client:
            workspace = modal.Workspace.from_context(client=client)
            while start < end:
                window_end = min(start + table.window_size, end)
                report = _report_with_rate_limit_retry(
                    workspace,
                    start=start,
                    end=window_end,
                    resolution=table.resolution,
                    tag_names=["*"],
                    safe_point=resumable_source_manager.safe_point,
                )
                ordered = sorted(report, key=lambda item: as_utc(item.interval_start))
                rows: list[dict[str, object]] = [
                    {
                        "object_id": item.object_id,
                        "description": item.description,
                        "environment_name": item.environment_name,
                        "interval_start": as_utc(item.interval_start),
                        "cost": float(item.cost),
                        "tags": dict(item.tags),
                    }
                    for item in ordered
                ]
                resumable_source_manager.save_state(
                    ModalResumeConfig(next_window_start=window_end.isoformat(), end=end.isoformat())
                )
                if rows:
                    yield rows
                resumable_source_manager.safe_point()
                start = window_end

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=BILLING_REPORT_PRIMARY_KEYS,
        column_hints={"cost": "double", "interval_start": "timestamp", "tags": "json"},
        partition_keys=[BILLING_REPORT_PARTITION_KEY],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
        on_complete=resumable_source_manager.clear_state,
    )


def billing_summary_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, object]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume:
            last_cycle = as_utc(resume.end)
            cycle = as_utc(resume.next_window_start)
        else:
            last_cycle = month_start(datetime.now(UTC))
            watermark = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            # Re-read the watermark cycle because its cost changes until the cycle is invoiced.
            cycle = (
                month_start(as_utc(watermark))
                if watermark is not None
                else add_months(last_cycle, 1 - BILLING_SUMMARY_DEFAULT_CYCLES)
            )

        if cycle > last_cycle:
            return

        with billing_client(config) as client:
            billing = modal.Workspace.from_context(client=client).billing
            while cycle <= last_cycle:
                summary = billing.summary(cycle=cycle)
                next_cycle = add_months(cycle, 1)
                resumable_source_manager.save_state(
                    ModalResumeConfig(next_window_start=next_cycle.isoformat(), end=last_cycle.isoformat())
                )
                yield [
                    {
                        "cycle_start": as_utc(summary.start),
                        "cycle_end": as_utc(summary.end),
                        "metered_cost": float(summary.metered_cost),
                        "billed_cost": float(summary.billed_cost),
                        "metered_cost_breakdown": {
                            key: float(value) for key, value in summary.metered_cost_breakdown.items()
                        },
                        "adjustments": {key: float(value) for key, value in summary.adjustments.items()},
                    }
                ]
                cycle = next_cycle

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=["cycle_start"],
        column_hints={
            "cycle_start": "timestamp",
            "cycle_end": "timestamp",
            "metered_cost": "double",
            "billed_cost": "double",
            "metered_cost_breakdown": "json",
            "adjustments": "json",
        },
        sort_mode="asc",
        on_complete=resumable_source_manager.clear_state,
    )


def app_row(app: api_pb2.AppListResponse.AppListItem, environment_name: str) -> dict[str, object]:
    return {
        "app_id": app.app_id,
        "name": app.name or None,
        "description": app.description or None,
        "state": enum_label(api_pb2.AppState.DESCRIPTOR, app.state, "APP_STATE_"),
        "environment_name": environment_name,
        "created_at": from_epoch(app.created_at),
        "stopped_at": from_epoch(app.stopped_at),
        "n_running_tasks": app.n_running_tasks,
    }


def apps_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, object]]]:
        with billing_client(config) as client:
            for environment in list_environments(client=client):
                rows = [app_row(app, environment.name) for app in list_apps(client, environment.name)]
                if rows:
                    yield rows
                resumable_source_manager.safe_point()

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=["app_id"],
        column_hints={"created_at": "timestamp", "stopped_at": "timestamp"},
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="month",
    )


def sandbox_row(sandbox: api_pb2.SandboxInfo, environment_name: str) -> dict[str, object]:
    task = sandbox.task_info
    resources = sandbox.resource_info
    finished = task.result.status != api_pb2.GenericResult.GENERIC_STATUS_UNSPECIFIED
    return {
        "id": sandbox.id,
        "name": sandbox.name or None,
        "app_id": sandbox.app_id,
        "environment_name": environment_name,
        "image_id": sandbox.image_id or None,
        "created_at": from_epoch(sandbox.created_at),
        "ready_at": from_epoch(sandbox.ready_at) if sandbox.HasField("ready_at") else None,
        "task_id": task.id or None,
        "enqueued_at": from_epoch(task.enqueued_at),
        "started_at": from_epoch(task.started_at),
        "finished_at": from_epoch(task.finished_at),
        "status": enum_label(api_pb2.GenericResult.GenericStatus.DESCRIPTOR, task.result.status, "GENERIC_STATUS_")
        if finished
        else None,
        "exit_code": task.result.exitcode if finished else None,
        "gpu_type": resources.gpu_type or task.gpu_type or None,
        "milli_cpu": resources.milli_cpu.value or None,
        "milli_cpu_max": resources.milli_cpu_max or None,
        "memory_mb": resources.memory_mb.value or None,
        "memory_mb_max": resources.memory_mb_max or None,
        "ephemeral_disk_mb": resources.ephemeral_disk_mb or None,
        "regions": list(sandbox.regions),
        "timeout_secs": sandbox.timeout_secs or None,
        "idle_timeout_secs": sandbox.idle_timeout_secs if sandbox.HasField("idle_timeout_secs") else None,
        "tags": {tag.tag_name: tag.tag_value for tag in sandbox.tags},
    }


def sandboxes_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, object]]]:
        with billing_client(config) as client:
            for environment in list_environments(client=client):
                # Listing by App follows the SDK, which deprecates Environment-wide Sandbox scans.
                for app in list_apps(client, environment.name):
                    # Zero leaves the cursor unset, so the first page starts at the newest Sandbox.
                    before_timestamp = 0.0
                    while True:
                        page = list_sandbox_page(client, app.app_id, environment.name, before_timestamp)
                        if page:
                            yield [sandbox_row(sandbox, environment.name) for sandbox in page]
                        resumable_source_manager.safe_point()
                        # Pages run newest first; stop if the cursor does not move back in time.
                        if not page or (before_timestamp and page[-1].created_at >= before_timestamp):
                            break
                        before_timestamp = page[-1].created_at

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=["id"],
        column_hints={
            "created_at": "timestamp",
            "ready_at": "timestamp",
            "enqueued_at": "timestamp",
            "started_at": "timestamp",
            "finished_at": "timestamp",
            "regions": "json",
            "tags": "json",
        },
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="month",
    )


# Apps in these states come from `modal run` or `modal serve`, which never deploy.
UNDEPLOYED_APP_STATES = frozenset(
    {
        api_pb2.APP_STATE_EPHEMERAL,
        api_pb2.APP_STATE_DETACHED,
        api_pb2.APP_STATE_DETACHED_DISCONNECTED,
    }
)


def strip_url_credentials(url: str) -> str:
    # The SDK copies the Git origin verbatim, so an HTTPS origin can carry an access token.
    parts = urlsplit(url)
    if not parts.scheme or "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def deployment_row(
    deployment: api_pb2.AppDeploymentHistory,
    app: api_pb2.AppListResponse.AppListItem,
    environment_name: str,
    production_version: int,
) -> dict[str, object]:
    has_commit = deployment.HasField("commit_info")
    commit = deployment.commit_info
    return {
        "app_id": app.app_id,
        "app_name": app.name or None,
        "environment_name": environment_name,
        "version": deployment.version,
        "is_production": deployment.version == production_version,
        "deployed_at": from_epoch(deployment.deployed_at),
        "deployed_by": deployment.deployed_by or None,
        "client_version": deployment.client_version or None,
        "tag": deployment.tag or None,
        "deployment_type": enum_label(
            api_pb2.DeploymentType.DESCRIPTOR, deployment.deployment_type, "DEPLOYMENT_TYPE_"
        ),
        "rollback_version": deployment.rollback_version or None,
        "rollback_allowed": deployment.rollback_allowed,
        "commit_hash": commit.commit_hash or None,
        "commit_branch": commit.branch or None,
        "commit_repo_url": strip_url_credentials(commit.repo_url) or None,
        "commit_dirty": commit.dirty if has_commit else None,
        "commit_author_name": commit.author_name or None,
        "committed_at": from_epoch(commit.commit_timestamp),
    }


def app_deployments_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, object]]]:
        with billing_client(config) as client:
            for environment in list_environments(client=client):
                for app in list_apps(client, environment.name):
                    if app.state in UNDEPLOYED_APP_STATES:
                        continue
                    try:
                        history = get_deployment_history(client, app.app_id)
                    except NotFoundError:
                        # The App can be deleted after the listing.
                        history = None
                    if history and history.app_deployment_histories:
                        yield [
                            deployment_row(deployment, app, environment.name, history.production_app_version)
                            for deployment in history.app_deployment_histories
                        ]
                    resumable_source_manager.safe_point()

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=["app_id", "version"],
        column_hints={"deployed_at": "timestamp", "committed_at": "timestamp"},
        partition_keys=["deployed_at"],
        partition_mode="datetime",
        partition_format="month",
    )


def member_row(member: api_pb2.WorkspaceMembersListItem) -> dict[str, object]:
    return {
        "user_id": member.user_id,
        "name": member.member_displayname or None,
        "email": member.email or None,
        "role": enum_label(api_pb2.MemberRole.DESCRIPTOR, member.member_role, "MEMBER_ROLE_"),
        "identity_provider": enum_label(
            api_pb2.IdentityProviderType.DESCRIPTOR, member.identity_provider_type, "IDENTITY_PROVIDER_TYPE_"
        ),
        "joined_at": from_epoch(member.joined_at),
        "last_active_at": from_epoch(member.last_active_at),
        "deleted_at": from_epoch(member.deleted_at),
    }


def workspace_members_source(config: ModalSourceConfig, inputs: SourceInputs) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, object]]]:
        with billing_client(config) as client:
            members = list_workspace_members(client)
        if members:
            yield [member_row(member) for member in members]

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=["user_id"],
        column_hints={"joined_at": "timestamp", "last_active_at": "timestamp", "deleted_at": "timestamp"},
    )
