from __future__ import annotations

from dataclasses import field, replace
from typing import TYPE_CHECKING

import structlog
from prometheus_client import Counter
from rest_framework import status

from posthog.hogql.errors import QueryError

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.facade.contracts import TrinoCompiledQuery, TrinoExpansionMode
from products.managed_warehouse.backend.facade.cp_teams import get_org_team_membership
from products.managed_warehouse.backend.table_binding import build_trino_table_locators

if TYPE_CHECKING:
    from collections.abc import Callable

    from posthog.schema import HogQLQuery, HogQLQueryModifiers

    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.transforms.trino.manifest import PreparedTrinoCatalog, TrinoCatalogManifest

    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

TRINO_COMPILATION_TOTAL = Counter(
    "managed_warehouse_trino_compilation_total",
    "Managed warehouse Trino compilations by semantic expansion mode.",
    labelnames=["mode"],
)
TRINO_PURE_REJECTION_TOTAL = Counter(
    "managed_warehouse_trino_pure_rejection_total",
    "Pure managed warehouse Trino compilation rejections by stable feature code.",
    labelnames=["feature_code"],
)


class TrinoTargetUnavailable(QueryError):
    feature_code = "TRINO_TARGET_UNAVAILABLE"


@frozen
class PreparedTrinoCompiler:
    """A validated managed-warehouse target with reusable pure catalog metadata."""

    team_id: int
    organization_id: str
    catalog_name: str
    _catalog: PreparedTrinoCatalog = field(repr=False, compare=False)

    def compile(self, query: HogQLQuery, *, include_hogql: bool = False) -> TrinoCompiledQuery:
        from posthog.hogql.transforms.trino.errors import TrinoLoweringError  # noqa: PLC0415

        TRINO_COMPILATION_TOTAL.labels(mode=TrinoExpansionMode.PURE.value).inc()
        try:
            transpiled = self._catalog.transpile(
                query.query,
                values=query.values,
                filters=query.filters,
                variables=query.variables,
                modifiers=query.modifiers,
                limit_top_select=False,
                include_hogql=include_hogql,
            )
        except TrinoLoweringError as error:
            TRINO_PURE_REJECTION_TOTAL.labels(feature_code=error.feature_code).inc()
            raise
        return transpiled


def _reject_pure_compilation(error: Exception, *, feature_code: str) -> None:
    TRINO_PURE_REJECTION_TOTAL.labels(feature_code=feature_code).inc()
    raise error


def get_ready_trino_catalog_name(organization_id: str) -> str | None:
    """Return the control-plane-owned catalog only after its Trino target is ready."""
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    response = _request("GET", organization_id, "/trino", require_enabled=False)
    readiness_logger = logger.bind(organization_id=str(organization_id), status_code=response.status_code)
    if not status.is_success(response.status_code):
        readiness_logger.warning("trino_target_not_ready", reason="http_error")
        return None
    if not isinstance(response.data, dict):
        readiness_logger.warning(
            "trino_target_not_ready", reason="invalid_response", response_type=type(response.data).__name__
        )
        return None
    enabled = response.data.get("enabled")
    if not isinstance(enabled, bool):
        readiness_logger.warning(
            "trino_target_not_ready", reason="invalid_enabled", enabled_type=type(enabled).__name__
        )
        return None
    if not enabled:
        readiness_logger.info(
            "trino_target_not_ready",
            reason="not_enabled",
            enabled=enabled,
            enabled_type=type(enabled).__name__,
        )
        return None

    trino_status = response.data.get("status")
    if not isinstance(trino_status, dict):
        readiness_logger.warning(
            "trino_target_not_ready", reason="invalid_status", status_type=type(trino_status).__name__
        )
        return None
    state = trino_status.get("state")
    if state != "ready":
        readiness_logger.info(
            "trino_target_not_ready",
            reason="state_not_ready",
            state=state[:128] if isinstance(state, str) else None,
            state_type=type(state).__name__,
        )
        return None
    response_org = trino_status.get("org")
    if response_org is not None and str(response_org) != str(organization_id):
        readiness_logger.warning(
            "refusing_trino_catalog_for_mismatched_organization",
            reason="organization_mismatch",
            requested_organization_id=str(organization_id),
            response_organization_id=response_org[:128] if isinstance(response_org, str) else None,
            response_organization_id_type=type(response_org).__name__,
        )
        return None

    catalog_name = trino_status.get("trino_catalog_name") or trino_status.get("catalog")
    if not isinstance(catalog_name, str) or not catalog_name.strip():
        readiness_logger.warning(
            "trino_target_not_ready", reason="invalid_catalog", catalog_type=type(catalog_name).__name__
        )
        return None
    return catalog_name.strip()


def prepare_hogql_to_trino_compiler(
    team_id: int,
    *,
    team: Team | None = None,
    catalog_manifest: TrinoCatalogManifest | None = None,
) -> PreparedTrinoCompiler:
    from posthog.hogql.transforms.trino.errors import TrinoLoweringError  # noqa: PLC0415
    from posthog.hogql.transforms.trino.manifest import (  # noqa: PLC0415
        TrinoCatalogManifest,
        TrinoManifestTable,
        prepare_trino_catalog,
    )

    from posthog.models.team.team import Team  # noqa: PLC0415
    from posthog.week_start_day import WeekStartDay  # noqa: PLC0415

    team = team or Team.objects.get(pk=team_id)
    if team.pk != team_id:
        raise TrinoTargetUnavailable("The provided team does not match the requested project")

    organization_id = str(team.organization_id)
    catalog_name = get_ready_trino_catalog_name(organization_id)
    if catalog_name is None:
        raise TrinoTargetUnavailable("The organization does not have a ready Trino catalog")

    membership = get_org_team_membership(organization_id, team_id)
    if membership is None:
        raise TrinoTargetUnavailable("The project does not have an authoritative physical table mapping")
    if membership.team_id != team_id or str(membership.organization_id) != organization_id:
        raise TrinoTargetUnavailable("The physical table mapping does not match the requested project")

    additional_tables = catalog_manifest.tables if catalog_manifest is not None else ()
    if any(table.logical_name in {"events", "persons", "groups", "raw_groups"} for table in additional_tables):
        _reject_pure_compilation(
            TrinoLoweringError(
                "TRINO_PURE_CORE_TABLE_OVERRIDE",
                "core table manifest",
                detail="Managed warehouse compilation owns the events and persons physical mappings.",
            ),
            feature_code="TRINO_PURE_CORE_TABLE_OVERRIDE",
        )
    groups_tables = (
        tuple(
            TrinoManifestTable(
                logical_name=logical_name,
                locator=(catalog_name, "posthog", membership.table_names.groups_table),
            )
            for logical_name in ("groups", "raw_groups")
        )
        if membership.table_names.groups_table is not None
        else ()
    )
    pure_manifest = TrinoCatalogManifest(
        tables=(
            TrinoManifestTable(
                logical_name="events",
                locator=(catalog_name, "posthog", membership.table_names.events_table),
            ),
            TrinoManifestTable(
                logical_name="persons",
                locator=(catalog_name, "posthog", membership.table_names.persons_table),
            ),
            *groups_tables,
            *additional_tables,
        ),
        timezone=team.timezone,
        week_start_day=team.week_start_day or WeekStartDay.SUNDAY,
    )
    return PreparedTrinoCompiler(
        team_id=team_id,
        organization_id=organization_id,
        catalog_name=catalog_name,
        _catalog=prepare_trino_catalog(pure_manifest),
    )


def compile_hogql_to_trino_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    user_access_control: UserAccessControl | None = None,
    limit_top_select: bool = False,
    limit_context: LimitContext | None = None,
    bypass_warehouse_access_control: bool = False,
    include_hogql: bool = False,
    expansion_mode: TrinoExpansionMode = TrinoExpansionMode.PURE,
    catalog_manifest: TrinoCatalogManifest | None = None,
    select_transform: Callable[[ast.SelectQuery | ast.SelectSetQuery], ast.SelectQuery | ast.SelectSetQuery]
    | None = None,
) -> TrinoCompiledQuery:
    """Compile HogQL for the ready Trino catalog that serves the team's DuckLake data.

    Set ``bypass_warehouse_access_control`` only for trusted internal callers that compile
    without a user. This entry point does not execute the returned SQL or alter query routing.
    Set ``include_hogql`` to render normalized HogQL for diagnostics. Pure manifest-backed
    compilation is the default; select ``TrinoExpansionMode.DJANGO`` only when the query needs
    actions, cohorts, saved queries, variables, filters, or other Django-backed semantics.
    ``select_transform`` rewrites the parsed query after placeholders are replaced, so it sees the
    same AST the printer does. It needs ``TrinoExpansionMode.DJANGO``.
    """
    if expansion_mode == TrinoExpansionMode.PURE:
        if select_transform is not None:
            raise ValueError("A select transform needs Django expansion")
        return prepare_hogql_to_trino_compiler(
            team_id,
            team=team,
            catalog_manifest=catalog_manifest,
        ).compile(query, include_hogql=include_hogql)

    from posthog.hogql.transforms.trino.compiler import (  # noqa: PLC0415 -- loads the optional backend only for Trino compilation
        compilation_fingerprint,
        compile_trino_query,
    )

    context = prepare_django_trino_context(
        team_id,
        team=team,
        user=user,
        user_access_control=user_access_control,
        modifiers=query.modifiers,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )
    context.limit_top_select = limit_top_select
    context.limit_context = limit_context
    TRINO_COMPILATION_TOTAL.labels(mode=expansion_mode.value).inc()
    compiled = compile_trino_query(
        query.query,
        context=context,
        expansion_mode=expansion_mode,
        values=query.values,
        filters=query.filters,
        variables=query.variables,
        modifiers=query.modifiers,
        include_hogql=include_hogql,
        select_transform=select_transform,
    )
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415

    model_definitions = dict(
        DataWarehouseSavedQuery.objects.filter(
            team_id=team_id,
            deleted=False,
            name__in=compiled.dependencies,
        ).values_list("name", "query")
    )
    return replace(
        compiled,
        fingerprint=compilation_fingerprint(
            {
                "compilation": compiled.fingerprint,
                "models": model_definitions,
            }
        ),
    )


def prepare_django_trino_context(
    team_id: int,
    *,
    team: Team | None = None,
    user: User | None = None,
    user_access_control: UserAccessControl | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    bypass_warehouse_access_control: bool = False,
) -> HogQLContext:
    from posthog.hogql.context import HogQLContext  # noqa: PLC0415
    from posthog.hogql.database.database import Database  # noqa: PLC0415
    from posthog.hogql.modifiers import create_default_modifiers_for_team  # noqa: PLC0415

    from posthog.models.team.team import Team  # noqa: PLC0415

    team = team or Team.objects.get(pk=team_id)
    if team.pk != team_id:
        raise TrinoTargetUnavailable("The provided team does not match the requested project")
    organization_id = str(team.organization_id)
    catalog_name = get_ready_trino_catalog_name(organization_id)
    if catalog_name is None:
        raise TrinoTargetUnavailable("The organization does not have a ready Trino catalog")
    membership = get_org_team_membership(organization_id, team_id)
    if (
        membership is None
        or not membership.enabled
        or membership.team_id != team_id
        or str(membership.organization_id) != organization_id
    ):
        raise TrinoTargetUnavailable("The project does not have an authoritative physical table mapping")
    effective_modifiers = create_default_modifiers_for_team(team, modifiers)
    database = Database.create_for(
        team_id,
        team=team,
        user=user,
        user_access_control=user_access_control,
        modifiers=effective_modifiers,
        # Preserve an explicit trusted-internal bypass; the public default remains fail-closed.
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        trigger="trino",
    )
    return HogQLContext(
        team_id=team_id,
        team=team,
        user=user,
        user_access_control=user_access_control,
        enable_select_queries=True,
        limit_top_select=False,
        modifiers=effective_modifiers,
        database=database,
        # Match the access-controlled database above instead of widening it during resolution.
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        trino_table_locators=build_trino_table_locators(
            database,
            team_id,
            catalog_name=catalog_name,
            table_names=membership.table_names,
        ),
    )


def is_managed_trino_editor_connection(team_id: int, connection_id: str) -> bool:
    from posthog.ph_client import feature_enabled_or_false  # noqa: PLC0415

    from products.warehouse_sources.backend.facade.models import ExternalDataSource  # noqa: PLC0415

    source = ExternalDataSource.objects.filter(team_id=team_id, id=connection_id, deleted=False).first()
    if source is None or not source.is_dynamic_managed_warehouse:
        return False
    return feature_enabled_or_false(
        "managed-warehouse-trino-editor",
        str(team_id),
        groups={"organization": str(source.team.organization_id), "project": str(team_id)},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
