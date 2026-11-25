"""Show which recent warehouse records pass a source filter. Creates no signals, calls no AI and moves no cursor."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import structlog
from pydantic import JsonValue

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.errors import ExposedHogQLError, TableAccessDeniedError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.models import Team, User

from products.signals.backend.emission.fetchers.data_warehouse import FILTER_SOURCE_ALIAS, scope_ids_from_source_config
from products.signals.backend.emission.registry import (
    SignalSourceTableConfig,
    get_signal_config,
    warehouse_source_types_for,
)
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError
from products.signals.backend.filter_recipes import WarehouseFilterBindings
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.source_filters import SourceFilterPreviewStatus, WritableSource, writable_source
from products.warehouse_sources.backend.facade import api as warehouse_sources

logger = structlog.get_logger(__name__)

PREVIEW_LOOKBACK_DAYS = 7
PREVIEW_SAMPLE_LIMIT = 10
PREVIEW_TIMEOUT_S = 20

_PASSES = "__preview_passes"
_MALFORMED = "__preview_malformed"
_CREATED_AT = "__preview_created_at"
_FIELD_PREFIX = "__preview_field_"
_OLDEST = datetime.min.replace(tzinfo=UTC)


@frozen
class PreviewRecordColumns:
    id: str
    identifier: str
    title: str
    url: str


# The columns that identify a record to a person. A source without an entry has no preview.
_RECORD_COLUMNS: Mapping[tuple[str, str], PreviewRecordColumns] = {
    (SignalSourceProduct.LINEAR, SignalSourceType.ISSUE): PreviewRecordColumns(
        id="id", identifier="identifier", title="title", url="url"
    ),
}


@frozen
class PreviewRecord:
    id: str
    identifier: str | None
    title: str | None
    url: str | None
    created_at: datetime | None
    passes: bool
    malformed: bool
    fields: dict[str, JsonValue]


@frozen
class SourceFilterPreview:
    status: SourceFilterPreviewStatus
    error: str | None
    catalog_version: int
    lookback_days: int
    error_code: str | None = None
    error_start: int | None = None
    error_end: int | None = None
    total_count: int = 0
    passing_count: int = 0
    malformed_count: int = 0
    passing: tuple[PreviewRecord, ...] = ()
    excluded: tuple[PreviewRecord, ...] = ()

    @property
    def excluded_count(self) -> int:
        return self.total_count - self.passing_count


@frozen
class _EmittingSchema:
    table_id: UUID | None
    config: SignalSourceTableConfig


@frozen
class _PreviewTable:
    name: str
    config: SignalSourceTableConfig


def preview_source_filter(
    *,
    team: Team,
    user: User,
    source_product: str,
    source_type: str,
    expression: str,
    scope_ids: list[str] | None = None,
) -> SourceFilterPreview:
    """Evaluate an unsaved expression against the records emission would read over the lookback window.

    `scope_ids` replaces the source's saved allowlist when it is not None. Pass validated, stripped ids.

    Raises `FilterValidationError("not_available")` when this organization cannot write the source's filter.
    The query runs as `user`, under warehouse access control, unlike emission, which reads as the system.
    """
    source = writable_source(
        organization_id=str(team.organization_id), source_product=source_product, source_type=source_type
    )
    record_columns = _RECORD_COLUMNS.get((source_product, source_type))
    if record_columns is None:
        raise FilterValidationError("not_available", "Filters cannot be previewed for this source.")

    def outcome(status: SourceFilterPreviewStatus, error: str | None = None) -> SourceFilterPreview:
        return SourceFilterPreview(
            status=status, error=error, catalog_version=source.catalog_version, lookback_days=PREVIEW_LOOKBACK_DAYS
        )

    try:
        FilterExpression(expression, source.field_types)
    except FilterValidationError as error:
        return replace(
            outcome(SourceFilterPreviewStatus.INVALID_EXPRESSION, str(error)),
            error_code=error.code,
            error_start=error.start,
            error_end=error.end,
        )

    schemas = _emitting_schemas(team.pk, source_product, source_type)
    if not schemas:
        return outcome(SourceFilterPreviewStatus.NOT_CONNECTED)
    table_keys = warehouse_sources.all_queryable_table_keys(team.pk)
    tables = [
        _PreviewTable(name=table_keys[schema.table_id].queryable_key, config=schema.config)
        for schema in schemas
        if schema.table_id is not None and schema.table_id in table_keys
    ]
    if not tables:
        return outcome(SourceFilterPreviewStatus.NOT_SYNCED)

    source_config = (
        SignalSourceConfig.objects.filter(team_id=team.pk, source_product=source_product, source_type=source_type)
        .values_list("config", flat=True)
        .first()
    )
    database = Database.create_for(team=team, user=user)
    previews: list[SourceFilterPreview] = []
    for table in tables:
        try:
            previews.append(
                _preview_table(
                    team, user, database, source, record_columns, table, expression, source_config, scope_ids
                )
            )
        except TableAccessDeniedError:
            return outcome(SourceFilterPreviewStatus.ACCESS_DENIED)
        except FilterValidationError as error:
            return outcome(SourceFilterPreviewStatus.INCOMPATIBLE_TABLE, str(error))
        except Exception as error:
            logger.warning(
                "signals.source_filter_preview.query_failed",
                team_id=team.pk,
                source_product=source_product,
                source_type=source_type,
                error_type=type(error).__name__,
            )
            # Other errors can carry generated SQL, so only an exposed error reaches the caller as written.
            exposed = isinstance(error, ExposedHogQLError | ExposedCHQueryError)
            return outcome(
                SourceFilterPreviewStatus.QUERY_FAILED, str(error) if exposed else "The preview could not run."
            )
    return _combine(source, previews)


def _emitting_schemas(team_id: int, source_product: str, source_type: str) -> list[_EmittingSchema]:
    """The team's syncing schemas whose rows become this source's signals, each with its emission config."""
    warehouse_source_types = warehouse_source_types_for(source_product, source_type)
    matched: list[_EmittingSchema] = []
    for warehouse_source in warehouse_sources.list_sources(team_id):
        if warehouse_source.source_type not in warehouse_source_types:
            continue
        for schema in warehouse_sources.list_schemas_for_source(warehouse_source.id, team_id):
            config = get_signal_config(warehouse_source.source_type, schema.name)
            if (
                schema.should_sync
                and config is not None
                and (config.source_product, config.source_type) == (source_product, source_type)
            ):
                matched.append(_EmittingSchema(table_id=schema.table_id, config=config))
    return matched


def _preview_table(
    team: Team,
    user: User,
    database: Database,
    source: WritableSource,
    record_columns: PreviewRecordColumns,
    table: _PreviewTable,
    expression: str,
    source_config: object,
    scope_ids_override: list[str] | None,
) -> SourceFilterPreview:
    columns = {
        name: field for name, field in database.get_table(table.name).fields.items() if isinstance(field, DatabaseField)
    }
    bindings = WarehouseFilterBindings(source.bundle, columns, source_alias=FILTER_SOURCE_ALIAS)
    predicate = bindings.predicate(expression)
    passes: ast.Expr = predicate.matches if predicate is not None else ast.Constant(value=True)
    malformed: ast.Expr = predicate.malformed if predicate is not None else ast.Constant(value=False)

    config = table.config
    conditions: list[ast.Expr] = [
        parse_expr(
            "{created_at} > now() - toIntervalDay({days})",
            placeholders={
                "created_at": parse_expr(config.partition_expression),
                "days": ast.Constant(value=PREVIEW_LOOKBACK_DAYS),
            },
        )
    ]
    if config.where_clause:
        conditions.append(parse_expr(config.where_clause))
    if config.emittable_where:
        conditions.append(parse_expr(config.emittable_where))
    scope_ids = (
        scope_ids_from_source_config(config, source_config) if scope_ids_override is None else scope_ids_override
    )
    if scope_ids and config.scope_field:
        conditions.append(
            parse_expr(
                "{scope} IN {scope_ids}",
                placeholders={
                    "scope": parse_expr(config.scope_field),
                    "scope_ids": ast.Tuple(exprs=[ast.Constant(value=scope_id) for scope_id in scope_ids]),
                },
            )
        )
    where = ast.And(exprs=conditions)

    table_chain: list[str | int] = [*table.name.split(".")]

    def source_table() -> ast.JoinExpr:
        return ast.JoinExpr(table=ast.Field(chain=list(table_chain)), alias=FILTER_SOURCE_ALIAS)

    counts_query = ast.SelectQuery(
        select=[
            ast.Call(name="count", args=[]),
            ast.Call(name="countIf", args=[clone_expr(passes)]),
            ast.Call(name="countIf", args=[clone_expr(malformed)]),
        ],
        select_from=source_table(),
        where=clone_expr(where),
    )
    counts = _execute(team, user, database, counts_query)
    total, passing, malformed_count = counts.results[0] if counts.results else (0, 0, 0)

    field_selects = [
        ast.Alias(
            alias=f"{_FIELD_PREFIX}{name}",
            # A malformed value would raise if read, so it reads as missing: null, or empty for an array.
            expr=ast.Call(
                name="if",
                args=[
                    clone_expr(projection.invalid),
                    ast.Array(exprs=[]) if projection.field.type == "array<string>" else ast.Constant(value=None),
                    clone_expr(projection.value),
                ],
            ),
        )
        for name, projection in bindings.projections.items()
    ]
    samples_query = ast.SelectQuery(
        select=[
            ast.Call(name="toString", args=[ast.Field(chain=[record_columns.id])]),
            ast.Field(chain=[record_columns.identifier]),
            ast.Field(chain=[record_columns.title]),
            ast.Field(chain=[record_columns.url]),
            ast.Alias(alias=_CREATED_AT, expr=parse_expr(config.partition_expression)),
            ast.Alias(alias=_PASSES, expr=clone_expr(passes)),
            ast.Alias(alias=_MALFORMED, expr=clone_expr(malformed)),
            *field_selects,
        ],
        select_from=source_table(),
        where=clone_expr(where),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=[_CREATED_AT]), order="DESC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=PREVIEW_SAMPLE_LIMIT), exprs=[ast.Field(chain=[_PASSES])]),
    )
    samples = _execute(team, user, database, samples_query)
    field_names = list(bindings.projections)
    records = [_record(row, field_names) for row in samples.results or []]
    return SourceFilterPreview(
        status=SourceFilterPreviewStatus.OK,
        error=None,
        catalog_version=source.catalog_version,
        lookback_days=PREVIEW_LOOKBACK_DAYS,
        total_count=int(total),
        passing_count=int(passing),
        malformed_count=int(malformed_count),
        passing=tuple(record for record in records if record.passes),
        excluded=tuple(record for record in records if not record.passes),
    )


def _execute(
    team: Team, user: User, database: Database, query: ast.SelectQuery | ast.SelectSetQuery
) -> HogQLQueryResponse:
    with tags_context(product=Product.SIGNALS, feature=Feature.QUERY, team_id=team.pk):
        return execute_hogql_query(
            query=query,
            team=team,
            user=user,
            query_type="SignalSourceFilterPreview",
            context=HogQLContext(team_id=team.pk, database=database, user=user),
            workload=Workload.ONLINE,
            settings=HogQLGlobalSettings(max_execution_time=PREVIEW_TIMEOUT_S),
        )


def _record(row: tuple[object, ...], field_names: list[str]) -> PreviewRecord:
    record_id, identifier, title, url, created_at, passes, malformed, *field_values = row
    return PreviewRecord(
        id=str(record_id),
        identifier=None if identifier is None else str(identifier),
        title=None if title is None else str(title),
        url=None if url is None else str(url),
        created_at=created_at if isinstance(created_at, datetime) else None,
        passes=bool(passes),
        malformed=bool(malformed),
        fields={name: cast(JsonValue, value) for name, value in zip(field_names, field_values)},
    )


def _combine(source: WritableSource, previews: list[SourceFilterPreview]) -> SourceFilterPreview:
    def newest(records: list[PreviewRecord]) -> tuple[PreviewRecord, ...]:
        ordered = sorted(records, key=lambda record: record.created_at or _OLDEST, reverse=True)
        return tuple(ordered[:PREVIEW_SAMPLE_LIMIT])

    return SourceFilterPreview(
        status=SourceFilterPreviewStatus.OK,
        error=None,
        catalog_version=source.catalog_version,
        lookback_days=PREVIEW_LOOKBACK_DAYS,
        total_count=sum(preview.total_count for preview in previews),
        passing_count=sum(preview.passing_count for preview in previews),
        malformed_count=sum(preview.malformed_count for preview in previews),
        passing=newest([record for preview in previews for record in preview.passing]),
        excluded=newest([record for preview in previews for record in preview.excluded]),
    )
