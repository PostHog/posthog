import re
from collections.abc import Iterator

from posthog.schema_enums import DataWarehouseSavedQueryOrigin

from products.data_modeling.backend.facade.api import (
    HasDependentsError,
    check_saved_query_deletable,
    saved_query_definitions,
)
from products.data_modeling.backend.facade.contracts import Dependent, SavedQueryDefinition
from products.endpoints.backend.models import EndpointVersion


class EndpointMaterializationDependencyService:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        self._saved_query_readers: list[SavedQueryDefinition] | None = None
        self._endpoint_readers: list[EndpointVersion] | None = None

    def check_deletable(self, version: EndpointVersion) -> None:
        saved_query = version.saved_query
        if saved_query is None:
            return

        dag_dependents: tuple[Dependent, ...] = ()
        fallback_node_id: str | None = None
        try:
            check_saved_query_deletable(self.team_id, saved_query.id)
        except HasDependentsError as error:
            dag_dependents = error.dependents
            fallback_node_id = error.fallback_node_id

        dependents = self._deduplicate(
            [*dag_dependents, *self._fallback_dependents(version, saved_query.name, str(saved_query.id))]
        )
        if dependents:
            raise HasDependentsError(saved_query.name, dependents, fallback_node_id=fallback_node_id)

    def _fallback_dependents(
        self, source_version: EndpointVersion, saved_query_name: str, saved_query_id: str
    ) -> Iterator[Dependent]:
        name_pattern = re.compile(rf"(?<![\w$]){re.escape(saved_query_name)}(?![\w$])")

        for definition in self._get_saved_query_readers():
            if (
                str(definition.id) != saved_query_id
                and definition.origin != DataWarehouseSavedQueryOrigin.ENDPOINT
                and name_pattern.search(definition.hogql)
            ):
                yield Dependent(
                    name=definition.name,
                    kind="matview" if definition.materializes else "view",
                    saved_query_id=str(definition.id),
                )

        for reader in self._get_endpoint_readers():
            if reader.id != source_version.id and self._query_references(reader.query, saved_query_name, name_pattern):
                yield Dependent(
                    name=reader.materialized_view_name if reader.saved_query_id else reader.endpoint.name,
                    kind="endpoint",
                    saved_query_id=str(reader.saved_query_id) if reader.saved_query_id else None,
                    created_by_id=reader.endpoint.created_by_id,
                )

    def _get_saved_query_readers(self) -> list[SavedQueryDefinition]:
        if self._saved_query_readers is None:
            self._saved_query_readers = saved_query_definitions(self.team_id)
        return self._saved_query_readers

    def _get_endpoint_readers(self) -> list[EndpointVersion]:
        if self._endpoint_readers is None:
            self._endpoint_readers = list(
                EndpointVersion.objects.filter(
                    endpoint__team_id=self.team_id,
                    endpoint__deleted=False,
                    endpoint__is_active=True,
                    is_active=True,
                )
                .select_related("endpoint")
                .order_by("created_at", "id")
            )
        return self._endpoint_readers

    @classmethod
    def _query_references(cls, value: object, table_name: str, name_pattern: re.Pattern[str]) -> bool:
        if isinstance(value, dict):
            if value.get("kind") == "HogQLQuery" and isinstance(value.get("query"), str):
                if name_pattern.search(value["query"]):
                    return True
            if str(value.get("kind", "")).endswith("DataWarehouseNode") and value.get("table_name") == table_name:
                return True
            return any(cls._query_references(child, table_name, name_pattern) for child in value.values())
        if isinstance(value, list):
            return any(cls._query_references(child, table_name, name_pattern) for child in value)
        return False

    @staticmethod
    def _deduplicate(dependents: list[Dependent]) -> tuple[Dependent, ...]:
        unique: dict[tuple[str, str], Dependent] = {}
        for dependent in dependents:
            key = (dependent.kind, dependent.saved_query_id or dependent.name)
            unique.setdefault(key, dependent)
        return tuple(unique.values())
