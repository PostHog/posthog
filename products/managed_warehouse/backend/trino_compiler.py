from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from rest_framework import status

from products.managed_warehouse.backend.facade.contracts import TrinoCompiledQuery
from products.managed_warehouse.backend.facade.cp_teams import get_org_team_membership
from products.managed_warehouse.backend.table_binding import build_trino_table_locators

if TYPE_CHECKING:
    from posthog.schema import HogQLQuery

    from posthog.models import Team, User

logger = structlog.get_logger(__name__)


class TrinoTargetUnavailable(RuntimeError):
    pass


def get_ready_trino_catalog_name(organization_id: str) -> str | None:
    """Return the control-plane-owned catalog only after its Trino target is ready."""
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    response = _request("GET", organization_id, "/trino", require_enabled=False)
    if not status.is_success(response.status_code) or not isinstance(response.data, dict):
        return None
    if response.data.get("enabled") is not True:
        return None

    trino_status = response.data.get("status")
    if not isinstance(trino_status, dict) or trino_status.get("state") != "ready":
        return None
    response_org = trino_status.get("org")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "refusing_trino_catalog_for_mismatched_organization",
            requested_organization_id=str(organization_id),
            response_organization_id=str(response_org),
        )
        return None

    catalog_name = trino_status.get("trino_catalog_name") or trino_status.get("catalog")
    return catalog_name.strip() if isinstance(catalog_name, str) and catalog_name.strip() else None


def compile_hogql_to_trino_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
    include_hogql: bool = False,
) -> TrinoCompiledQuery:
    """Compile HogQL for the ready Trino catalog that serves the team's DuckLake data.

    Set ``bypass_warehouse_access_control`` only for trusted internal callers that compile
    without a user. This entry point does not execute the returned SQL or alter query routing.
    Set ``include_hogql`` to render normalized HogQL for diagnostics.
    """
    from posthog.hogql import ast  # noqa: PLC0415
    from posthog.hogql.context import HogQLContext  # noqa: PLC0415
    from posthog.hogql.database.database import Database  # noqa: PLC0415
    from posthog.hogql.filters import replace_filters  # noqa: PLC0415
    from posthog.hogql.modifiers import create_default_modifiers_for_team  # noqa: PLC0415
    from posthog.hogql.parser import parse_select, sanitize_client_parser_mode  # noqa: PLC0415
    from posthog.hogql.placeholders import find_placeholders, replace_placeholders  # noqa: PLC0415
    from posthog.hogql.printer.utils import prepare_and_print_ast  # noqa: PLC0415
    from posthog.hogql.variables import replace_variables  # noqa: PLC0415
    from posthog.hogql.visitor import clone_expr  # noqa: PLC0415

    from posthog.models.team.team import Team  # noqa: PLC0415

    team = team or Team.objects.get(pk=team_id)
    organization_id = str(team.organization_id)
    catalog_name = get_ready_trino_catalog_name(organization_id)
    if catalog_name is None:
        raise TrinoTargetUnavailable("The organization does not have a ready Trino catalog")

    membership = get_org_team_membership(organization_id, team_id)
    if membership is None:
        raise TrinoTargetUnavailable("The project does not have an authoritative physical table mapping")

    query_modifiers = create_default_modifiers_for_team(team, query.modifiers)
    placeholder_values: dict[str, ast.Expr] | None = (
        {key: ast.Constant(value=value) for key, value in query.values.items()} if query.values else None
    )
    parsed = parse_select(
        query.query,
        placeholders=placeholder_values,
        parser_mode=sanitize_client_parser_mode(query_modifiers.parserMode),
    )

    database = Database.create_for(
        team_id,
        team=team,
        user=user,
        modifiers=query_modifiers,
        # Preserve an explicit trusted-internal bypass; the public default remains fail-closed.
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        trigger="trino",
    )
    placeholders = find_placeholders(parsed)
    if placeholders.has_filters:
        parsed = replace_filters(parsed, query.filters, team, database=database)
    if query.variables:
        parsed = replace_variables(parsed, list(query.variables.values()), team)
    if placeholders.placeholder_fields or placeholders.placeholder_expressions:
        variables: dict[str, Any] = {}
        replacements: dict[str, Any] = {"variables": variables, **(placeholder_values or {})}
        if query.variables:
            for variable in query.variables.values():
                variables[variable.code_name] = variable.value
        parsed = cast("ast.SelectQuery | ast.SelectSetQuery", replace_placeholders(parsed, replacements))

    trino_table_locators = build_trino_table_locators(
        database,
        team_id,
        catalog_name=catalog_name,
        table_names=membership.table_names,
    )
    trino_context = HogQLContext(
        team_id=team_id,
        team=team,
        user=user,
        enable_select_queries=True,
        modifiers=query_modifiers,
        # Match the access-controlled database above instead of widening it during resolution.
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        database=database,
        trino_table_locators=trino_table_locators,
    )
    hogql_ast = clone_expr(parsed) if include_hogql else None
    trino_sql, _ = prepare_and_print_ast(parsed, trino_context, dialect="trino")

    hogql_pretty: str | None = None
    if hogql_ast is not None:
        hogql_context = HogQLContext(
            team_id=team_id,
            team=team,
            user=user,
            enable_select_queries=True,
            modifiers=query_modifiers,
            bypass_warehouse_access_control=bypass_warehouse_access_control,
            database=database,
        )
        hogql_pretty, _ = prepare_and_print_ast(hogql_ast, hogql_context, dialect="hogql")

    return TrinoCompiledQuery(sql=trino_sql, values=dict(trino_context.values), hogql=hogql_pretty)
