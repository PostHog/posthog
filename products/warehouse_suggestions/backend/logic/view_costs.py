from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.errors import ClickHouseQueryTimeOut
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.data_modeling.backend.facade.api import get_saved_query_columns, get_saved_query_summary

from .reads import MEASUREMENT_FEATURE
from .rules import MeasurementRules

MEASUREMENT_QUERY_NAME = "warehouse_suggestions_view_cost"
CAP_KEY_PREFIX = "warehouse_suggestions:view_cost_cap"
FAILED_MEASUREMENT = 0


class MeasurementOutcome(StrEnum):
    MEASURED = "measured"
    CAPPED = "capped"
    FAILED = "failed"
    GONE = "gone"


def measured_cap_seconds(team_id: int, saved_query_id: UUID) -> int | None:
    return cache.get(_cap_key(team_id, saved_query_id))


def measure_view_cost(team_id: int, saved_query_id: UUID, rules: MeasurementRules) -> MeasurementOutcome:
    summary = get_saved_query_summary(team_id, saved_query_id)
    column_names = list(get_saved_query_columns(team_id, saved_query_id))
    if summary is None or not column_names:
        return MeasurementOutcome.GONE
    tag_queries(
        product=Product.DATA_MODELING, feature=MEASUREMENT_FEATURE, team_id=team_id, name=MEASUREMENT_QUERY_NAME
    )
    try:
        execute_hogql_query(
            query=full_read_query(summary.name, column_names),
            team=Team.objects.get(id=team_id),
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=rules.max_seconds),
        )
    except ClickHouseQueryTimeOut:
        _remember_cap(team_id, saved_query_id, rules.max_seconds, rules)
        return MeasurementOutcome.CAPPED
    except Exception as error:
        capture_exception(error)
        _remember_cap(team_id, saved_query_id, FAILED_MEASUREMENT, rules)
        return MeasurementOutcome.FAILED
    return MeasurementOutcome.MEASURED


def full_read_query(view_name: str, column_names: list[str]) -> ast.SelectQuery:
    every_column = ast.Call(name="tuple", args=[ast.Field(chain=[name]) for name in column_names])
    row_hash = ast.Call(name="cityHash64", args=[ast.Call(name="toString", args=[every_column])])
    return ast.SelectQuery(
        select=[ast.Call(name="count", args=[]), ast.Call(name="sum", args=[row_hash])],
        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
    )


def _remember_cap(team_id: int, saved_query_id: UUID, seconds: int, rules: MeasurementRules) -> None:
    timeout = int(timedelta(days=rules.retry_after_days).total_seconds())
    cache.set(_cap_key(team_id, saved_query_id), seconds, timeout=timeout)


def _cap_key(team_id: int, saved_query_id: UUID) -> str:
    return f"{CAP_KEY_PREFIX}:{team_id}:{saved_query_id}"
