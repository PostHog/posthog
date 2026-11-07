"""Check which of a team's models the Trino shadow build can compile, without building any of them.

The compile stage calls the shadow build's own compiler entry point, so a model that passes here passes
the shadow build's compile step. The optional explain stage asks Trino to plan the compiled SQL, which
finds missing tables, type errors and functions the deployed Trino lacks. Nothing here writes data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from contextlib import nullcontext
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.dataclasses import frozen
from posthog.models import Team

from products.managed_warehouse.backend.trino_compiler import TrinoTargetUnavailable
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.managed_warehouse.backend.trino_materialization import compile_trino_shadow_query

if TYPE_CHECKING:
    from trino.dbapi import Connection

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

_MESSAGE_LIMIT = 300
_COMPILE_ERRORS = (BaseHogQLError, TrinoTargetUnavailable, ValidationError)


class TrinoCompileCheckStage(StrEnum):
    COMPILE = "compile"
    EXPLAIN = "explain"


@frozen
class TrinoCompileCheckRow:
    saved_query_id: str
    name: str
    stage: TrinoCompileCheckStage
    """The last stage that ran: the stage that failed, or the last stage that passed."""
    error_code: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


@frozen
class TrinoCompileCheckReport:
    rows: tuple[TrinoCompileCheckRow, ...]

    @property
    def ok_count(self) -> int:
        return sum(row.ok for row in self.rows)

    @property
    def error_counts(self) -> dict[str, int]:
        counts = Counter(row.error_code for row in self.rows if row.error_code is not None)
        return dict(counts.most_common())


def check_trino_compile(
    team: Team,
    *,
    saved_query_ids: Sequence[str] | None = None,
    explain: bool = False,
    limit: int | None = None,
    explain_timeout_seconds: int = 30,
) -> TrinoCompileCheckReport:
    """Compile each non-deleted saved query of ``team`` for Trino, and with ``explain`` let Trino plan it."""
    saved_queries = _load_saved_queries(team.pk, saved_query_ids, limit)
    connection_context = (
        connect_managed_warehouse_trino(
            str(team.organization_id), principal=f"posthog:trino-compile-check:team:{team.pk}"
        )
        if explain and saved_queries
        else nullcontext()
    )
    with connection_context as connection:
        if connection is not None:
            _limit_explain_time(connection, explain_timeout_seconds)
        rows = tuple(_check(team, saved_query, connection) for saved_query in saved_queries)
    return TrinoCompileCheckReport(rows=rows)


def _load_saved_queries(
    team_id: int, saved_query_ids: Sequence[str] | None, limit: int | None
) -> list[DataWarehouseSavedQuery]:
    from products.data_modeling.backend.facade.models import (  # noqa: PLC0415 -- the facade loads lazily
        DataWarehouseSavedQuery,
    )

    queryset = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).order_by("name")
    if saved_query_ids is not None:
        queryset = queryset.filter(id__in=saved_query_ids)
    return list(queryset[:limit] if limit is not None else queryset)


def _limit_explain_time(connection: Connection, timeout_seconds: int) -> None:
    # The planning limit misses queue time and analysis, so the run-time limit bounds the whole EXPLAIN.
    # Trino then fails the query with EXCEEDED_TIME_LIMIT. The client keeps the session properties.
    for setting in ("query_max_planning_time", "query_max_run_time"):
        cursor = connection.cursor()
        try:
            cursor.execute(f"SET SESSION {setting} = '{int(timeout_seconds)}s'")
            cursor.fetchall()
        finally:
            cursor.close()


def _check(team: Team, saved_query: DataWarehouseSavedQuery, connection: Connection | None) -> TrinoCompileCheckRow:
    from trino.exceptions import TrinoQueryError  # noqa: PLC0415 -- keeps the optional driver off startup paths

    saved_query_id, name = str(saved_query.id), saved_query.name
    # Endpoint models are rebuilt from their endpoint version before each build. That rebuild writes,
    # so the check reads the stored query, which is the last rebuild.
    try:
        compiled = compile_trino_shadow_query(team, HogQLQuery.model_validate(saved_query.query))
    except _COMPILE_ERRORS as error:
        code = error.feature_code if isinstance(error, TrinoLoweringError) else type(error).__name__
        return _failed(saved_query_id, name, TrinoCompileCheckStage.COMPILE, code, error)
    if connection is None:
        return TrinoCompileCheckRow(saved_query_id=saved_query_id, name=name, stage=TrinoCompileCheckStage.COMPILE)

    sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
    cursor = connection.cursor()
    try:
        cursor.execute(f"EXPLAIN {sql}", parameters or None)
        cursor.fetchall()
    except TrinoQueryError as error:
        code = error.error_name or type(error).__name__
        return _failed(saved_query_id, name, TrinoCompileCheckStage.EXPLAIN, code, error)
    finally:
        cursor.close()
    return TrinoCompileCheckRow(saved_query_id=saved_query_id, name=name, stage=TrinoCompileCheckStage.EXPLAIN)


def _failed(
    saved_query_id: str, name: str, stage: TrinoCompileCheckStage, code: str, error: Exception
) -> TrinoCompileCheckRow:
    message = getattr(error, "message", None) or str(error)
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    return TrinoCompileCheckRow(
        saved_query_id=saved_query_id,
        name=name,
        stage=stage,
        error_code=code,
        message=first_line[:_MESSAGE_LIMIT],
    )
