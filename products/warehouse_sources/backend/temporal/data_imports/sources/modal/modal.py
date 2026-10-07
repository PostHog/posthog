from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import modal
from grpclib import GRPCError, Status
from modal.exception import AuthError, PermissionDeniedError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.settings import (
    ENDPOINTS,
    PARTITION_KEY,
    PRIMARY_KEYS,
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


def modal_source(
    config: ModalSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
) -> SourceResponse:
    table = schema_for_resource(ENDPOINTS, inputs.schema_name)

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
                report = workspace.billing.report(
                    start=start, end=window_end, resolution=table.resolution, tag_names=["*"]
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
        primary_keys=PRIMARY_KEYS,
        column_hints={"cost": "double", "interval_start": "timestamp", "tags": "json"},
        partition_keys=[PARTITION_KEY],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
        on_complete=resumable_source_manager.clear_state,
    )
