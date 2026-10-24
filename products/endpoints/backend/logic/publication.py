from django.db import transaction

import structlog
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.variables import replace_variables

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.data_modeling.backend.facade.api import (
    get_node_ids_for_saved_queries,
    link_endpoint_nodes,
    sync_saved_query_to_dag,
)
from products.data_modeling.backend.facade.modeling import UnknownParentError
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Node
from products.data_quality.backend.facade.api import copy_checks_to_saved_query
from products.endpoints.backend.materialization_transforms import MaterializationNotSupportedError, build_endpoint_hogql
from products.endpoints.backend.models import Endpoint, EndpointVersion, can_materialize_query
from products.warehouse_sources.backend.facade.hogql import hogql_type_name_for_clickhouse_type

logger = structlog.get_logger(__name__)


@frozen
class EndpointModelDefinition:
    query: dict
    column_types: dict[str, str]


class EndpointModelService:
    def __init__(self, team: Team, user: User | None = None) -> None:
        self.team = team
        self.user = user

    def prepare_model(self, query: dict) -> EndpointModelDefinition | None:
        if query.get("kind") != "HogQLQuery" and not can_materialize_query(query)[0]:
            return None
        try:
            model_query = build_endpoint_hogql(query, self.team, user=self.user)
            if model_query.get("variables"):
                query_model = HogQLQuery.model_validate(model_query)
                resolved = replace_variables(
                    parse_select(query_model.query), list((query_model.variables or {}).values()), self.team
                )
                model_query = {
                    **model_query,
                    "query": prepare_and_print_ast(
                        resolved,
                        context=HogQLContext(
                            team=self.team,
                            team_id=self.team.pk,
                            user=self.user,
                            enable_select_queries=True,
                            limit_top_select=False,
                            modifiers=create_default_modifiers_for_team(self.team, query_model.modifiers),
                        ),
                        dialect="hogql",
                        pretty=True,
                    )[0],
                    "variables": {},
                }
        except (ExposedHogQLError, MaterializationNotSupportedError, PydanticValidationError):
            return None
        try:
            column_types = EndpointVersion.extract_column_types(model_query, self.team.pk)
        except Exception as error:
            capture_exception(error, {"team_id": self.team.pk})
            column_types = {}
        return EndpointModelDefinition(query=model_query, column_types=column_types)

    def get_or_build_saved_query(self, version: EndpointVersion) -> DataWarehouseSavedQuery:
        """Find this version's saved query, or build a new (unsaved) one.

        SECURITY: only adopt a saved query that this endpoint owns (ENDPOINT origin and not
        linked to a different version). Without this, a user-created saved query whose name
        happens to collide with {endpoint}_v{n} would be silently taken over — its query
        overwritten and served as the endpoint's data.
        """
        name = version.materialized_view_name
        existing = version.saved_query
        if existing is None:
            existing = DataWarehouseSavedQuery.objects.filter(name=name, team=self.team).exclude(deleted=True).first()
        if existing is None:
            return DataWarehouseSavedQuery(
                name=name,
                team=self.team,
                created_by_id=version.created_by_id or (self.user.pk if self.user else None),
                origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
            )

        is_foreign = (
            existing.team_id != self.team.pk
            or existing.origin != DataWarehouseSavedQuery.Origin.ENDPOINT
            or (EndpointVersion.objects.filter(saved_query=existing).exclude(pk=version.pk).exists())
        )
        if is_foreign:
            raise ValidationError(
                f"A saved query named '{name}' already exists and is not managed by this endpoint. "
                "Rename or delete it before publishing this version."
            )
        return existing

    def ensure_model(
        self,
        endpoint: Endpoint,
        version: EndpointVersion,
        previous_version: EndpointVersion | None = None,
        *,
        definition: EndpointModelDefinition | None,
    ) -> None:
        model_created = version.saved_query_id is None
        if model_created:
            if definition is None:
                return
            with transaction.atomic():
                saved_query = self.get_or_build_saved_query(version)
                saved_query.query = definition.query
                saved_query.set_columns(
                    {
                        name: {
                            "clickhouse": column_type,
                            "hogql": hogql_type_name_for_clickhouse_type(column_type),
                            "valid": True,
                        }
                        for name, column_type in definition.column_types.items()
                    }
                )
                saved_query.save()
                version.saved_query = saved_query
                version.save(update_fields=["saved_query", "updated_at"])
        assert version.saved_query is not None
        saved_query = version.saved_query
        try:
            with transaction.atomic():
                if model_created or not get_node_ids_for_saved_queries(self.team.pk, [saved_query.id]):
                    sync_saved_query_to_dag(saved_query, reconcile=bool(saved_query.is_materialized))
                link_endpoint_nodes(
                    team_id=self.team.pk,
                    saved_query_id=saved_query.id,
                    endpoint_name=endpoint.name,
                    version=version.version,
                )
        except (ExposedHogQLError, UnknownParentError, Node.DoesNotExist):
            logger.info("endpoint_model_lineage_unavailable", endpoint_id=str(endpoint.id), version=version.version)
        if model_created and previous_version and previous_version.saved_query_id:
            copy_checks_to_saved_query(self.team.pk, str(previous_version.saved_query_id), str(saved_query.id))
