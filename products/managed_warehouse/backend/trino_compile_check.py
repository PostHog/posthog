"""Check which of a team's models the Trino shadow build can compile, without building any of them.

The compile stage calls the shadow build's own compiler entry point, so a model that passes here passes
the shadow build's compile step. The optional explain stage asks Trino to plan the compiled SQL, which
finds missing tables, type errors and functions the deployed Trino lacks. Nothing here writes data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import nullcontext
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.escape_sql import escape_trino_string
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.dataclasses import frozen
from posthog.models import Team

from products.managed_warehouse.backend.trino_compiler import TrinoTarget, TrinoTargetUnavailable, resolve_trino_target
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.managed_warehouse.backend.trino_materialization import compile_trino_shadow_query

if TYPE_CHECKING:
    from trino.dbapi import Connection, Cursor

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
    skip_ids: Iterable[str] = (),
) -> Iterator[TrinoCompileCheckRow]:
    """Compile each non-deleted saved query of ``team`` for Trino, and with ``explain`` let Trino plan it.

    Yields one row per saved query as soon as it is checked, so a caller can keep partial results.
    """
    saved_queries = _load_saved_queries(team.pk, saved_query_ids, limit, skip_ids)
    target: TrinoTarget | TrinoTargetUnavailable | None = None
    if saved_queries:
        try:
            target = resolve_trino_target(team)
        except TrinoTargetUnavailable as error:
            target = error
    connection_context = (
        connect_managed_warehouse_trino(
            str(team.organization_id), principal=f"posthog:trino-compile-check:team:{team.pk}"
        )
        if explain and saved_queries
        else nullcontext()
    )
    with connection_context as connection:
        for saved_query in saved_queries:
            yield _check(team, saved_query, target, connection)


def _load_saved_queries(
    team_id: int, saved_query_ids: Sequence[str] | None, limit: int | None, skip_ids: Iterable[str]
) -> list[DataWarehouseSavedQuery]:
    from products.data_modeling.backend.facade.models import (  # noqa: PLC0415 -- the facade loads lazily
        DataWarehouseSavedQuery,
    )

    queryset = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).order_by("name")
    if saved_query_ids is not None:
        queryset = queryset.filter(id__in=saved_query_ids)
    queryset = queryset.exclude(id__in=list(skip_ids))
    return list(queryset[:limit] if limit is not None else queryset)


def _check(
    team: Team,
    saved_query: DataWarehouseSavedQuery,
    target: TrinoTarget | TrinoTargetUnavailable | None,
    connection: Connection | None,
) -> TrinoCompileCheckRow:
    from trino.exceptions import TrinoQueryError  # noqa: PLC0415 -- keeps the optional driver off startup paths

    saved_query_id, name = str(saved_query.id), saved_query.name
    # Endpoint models are rebuilt from their endpoint version before each build. That rebuild writes,
    # so the check reads the stored query, which is the last rebuild.
    if isinstance(target, TrinoTargetUnavailable):
        return _failed(saved_query_id, name, TrinoCompileCheckStage.COMPILE, type(target).__name__, target)
    try:
        compiled = compile_trino_shadow_query(team, HogQLQuery.model_validate(saved_query.query), target=target)
    except _COMPILE_ERRORS as error:
        code = error.feature_code if isinstance(error, TrinoLoweringError) else type(error).__name__
        return _failed(saved_query_id, name, TrinoCompileCheckStage.COMPILE, code, error)
    if connection is None:
        return TrinoCompileCheckRow(saved_query_id=saved_query_id, name=name, stage=TrinoCompileCheckStage.COMPILE)

    sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
    cursor = connection.cursor()
    try:
        cursor.execute(_explain_statement(cursor, sql, parameters))
        cursor.fetchall()
    except TrinoQueryError as error:
        code = error.error_name or type(error).__name__
        return _failed(saved_query_id, name, TrinoCompileCheckStage.EXPLAIN, code, error)
    finally:
        cursor.close()
    return TrinoCompileCheckRow(saved_query_id=saved_query_id, name=name, stage=TrinoCompileCheckStage.EXPLAIN)


def _explain_statement(cursor: Cursor, sql: str, parameters: list[object]) -> str:
    if not parameters:
        return f"EXPLAIN {sql}"
    # Trino plans the statement inside EXPLAIN without the values bound to the outer statement, so a
    # parameterized EXPLAIN fails with "Incorrect number of parameters". EXPLAIN EXECUTE IMMEDIATE binds the
    # values to the planned statement. The client formats them the same way when the shadow build executes.
    values = ", ".join(cursor._format_prepared_param(value) for value in parameters)
    return f"EXPLAIN EXECUTE IMMEDIATE {escape_trino_string(sql)} USING {values}"


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
