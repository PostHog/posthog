from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.errors import ClickHouseQueryTimeOut
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.data_modeling.backend.facade.api import get_saved_query_columns, saved_query_definitions

from .candidates.unmaterialize import effective_definition
from .reads import MEASUREMENT_FEATURE
from .rules import MeasurementRules

MEASUREMENT_QUERY_NAME = "warehouse_suggestions_view_cost"
UNFINISHED_KEY_PREFIX = "warehouse_suggestions:unfinished_view_cost"
FAILED_MEASUREMENT = 0


class MeasurementOutcome(StrEnum):
    MEASURED = "measured"
    CAPPED = "capped"
    FAILED = "failed"
    GONE = "gone"


@frozen
class UnfinishedMeasurement:
    seconds: int
    fingerprint: str

    @property
    def failed(self) -> bool:
        return self.seconds == FAILED_MEASUREMENT


def unfinished_measurement(team_id: int, saved_query_id: UUID) -> UnfinishedMeasurement | None:
    remembered = cache.get(_unfinished_key(team_id, saved_query_id))
    if not isinstance(remembered, dict):
        return None
    return UnfinishedMeasurement(seconds=remembered["seconds"], fingerprint=remembered["fingerprint"])


def measure_view_cost(team_id: int, saved_query_id: UUID, rules: MeasurementRules) -> MeasurementOutcome:
    definitions = saved_query_definitions(team_id, ids=[saved_query_id])
    if not definitions:
        return MeasurementOutcome.GONE
    definition = definitions[0]
    fingerprint = effective_definition(team_id, definition).fingerprint
    column_names = list(get_saved_query_columns(team_id, saved_query_id))
    if not column_names:
        _remember_unfinished(team_id, saved_query_id, rules, seconds=FAILED_MEASUREMENT, fingerprint=fingerprint)
        return MeasurementOutcome.FAILED
    tag_queries(
        product=Product.DATA_MODELING, feature=MEASUREMENT_FEATURE, team_id=team_id, name=MEASUREMENT_QUERY_NAME
    )
    try:
        execute_hogql_query(
            query=full_read_query(definition.name, column_names),
            team=Team.objects.get(id=team_id),
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=rules.max_seconds),
            bypass_warehouse_access_control=True,
        )
    except ClickHouseQueryTimeOut:
        _remember_unfinished(team_id, saved_query_id, rules, seconds=rules.max_seconds, fingerprint=fingerprint)
        return MeasurementOutcome.CAPPED
    except Exception as error:
        capture_exception(error)
        _remember_unfinished(team_id, saved_query_id, rules, seconds=FAILED_MEASUREMENT, fingerprint=fingerprint)
        return MeasurementOutcome.FAILED
    return MeasurementOutcome.MEASURED


def full_read_query(view_name: str, column_names: list[str]) -> ast.SelectQuery:
    every_column = ast.Call(name="tuple", args=[ast.Field(chain=[name]) for name in column_names])
    row_hash = ast.Call(name="cityHash64", args=[ast.Call(name="toString", args=[every_column])])
    return ast.SelectQuery(
        select=[ast.Call(name="count", args=[]), ast.Call(name="sum", args=[row_hash])],
        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
    )


def _remember_unfinished(
    team_id: int, saved_query_id: UUID, rules: MeasurementRules, *, seconds: int, fingerprint: str
) -> None:
    timeout = int(timedelta(days=rules.retry_after_days).total_seconds())
    cache.set(
        _unfinished_key(team_id, saved_query_id), {"seconds": seconds, "fingerprint": fingerprint}, timeout=timeout
    )


def _unfinished_key(team_id: int, saved_query_id: UUID) -> str:
    return f"{UNFINISHED_KEY_PREFIX}:{team_id}:{saved_query_id}"
