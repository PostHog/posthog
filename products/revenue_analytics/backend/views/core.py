import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Optional

from posthog.schema import DatabaseSchemaManagedViewTableKind, RevenueAnalyticsEventItem

from posthog.hogql import ast

from posthog.models.team.team import Team

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


@dataclass
class SourceHandle:
    type: Literal["events", "stripe"]
    team: Team
    source: Optional[ExternalDataSource] = None
    event: Optional[RevenueAnalyticsEventItem] = None


@dataclass
class BuiltQuery:
    # Stable key for naming: event name for events, table id (string) for warehouse
    key: str
    # Prefix used as source_label and to name the view
    prefix: str
    # HogQL AST for the view
    query: ast.Expr
    # Useful for debugging purposes, only asserted by in tests
    test_comments: str | None = None


# A builder is a function that takes a SourceHandle and returns a single BuiltQuery object
# This is the type of the builder functions in the sources/**/*.py files, transforming a source into a set of views.
# You can find all builder functions in the sources/**/*.py files, and they are registered in the sources/registry.py file.
Builder = dict[DatabaseSchemaManagedViewTableKind, Callable[[SourceHandle], BuiltQuery]]


def view_prefix_for_event(event: str) -> str:
    return f"revenue_analytics.events.{re.sub(r'[^a-zA-Z0-9]', '_', event)}"


def view_prefix_for_source(source: ExternalDataSource) -> str:
    if not source.prefix:
        return source.source_type.lower()
    prefix = source.prefix.strip("_")
    return f"{source.source_type.lower()}.{prefix}"
