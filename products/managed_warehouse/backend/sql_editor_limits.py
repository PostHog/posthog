from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.direct_sql.trino_adapter import DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.logic.console_usage import get_max_scan_bytes_per_query

SCAN_LIMIT_ERROR_NAME = "EXCEEDED_SCAN_LIMIT"
_BYTES_PER_GIB = 1024**3


@frozen
class SqlEditorLimits:
    timeout_seconds: int
    max_scan_bytes: int | None

    @property
    def session_properties(self) -> dict[str, str] | None:
        if self.max_scan_bytes is None:
            return None
        return {"query_max_scan_physical_bytes": f"{self.max_scan_bytes}B"}


_HOGQL_DEFAULT_MAX_EXECUTION_TIME = HogQLGlobalSettings.model_fields["max_execution_time"].default


def sql_editor_limits(organization_id: str, max_execution_time: int | None) -> SqlEditorLimits:
    # The HogQL default of 60 seconds is too short for warehouse scans, so an unset or default value gets the Trino
    # default. A value that a caller set on purpose, lower or higher, stays.
    timeout = (
        DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS
        if max_execution_time is None or max_execution_time == _HOGQL_DEFAULT_MAX_EXECUTION_TIME
        else max_execution_time
    )
    return SqlEditorLimits(
        timeout_seconds=timeout,
        max_scan_bytes=get_max_scan_bytes_per_query(organization_id),
    )


@contextmanager
def map_scan_limit_error(limits: SqlEditorLimits) -> Iterator[None]:
    try:
        yield
    except ExposedHogQLError as error:
        if limits.max_scan_bytes is None or getattr(error.__cause__, "error_name", None) != SCAN_LIMIT_ERROR_NAME:
            raise
        limit = f"{limits.max_scan_bytes / _BYTES_PER_GIB:.4g} GiB"
        raise ExposedHogQLError(
            f"This query would scan more than {limit}, your organization's per-query limit. "
            "Add filters or ask an admin to raise the limit in Warehouse usage."
        ) from error
