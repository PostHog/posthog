from typing import Any

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.schema_enums import MaterializedViewEngine

from products.data_modeling.backend.facade.contracts import MaterializationEngine
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node, NodeEngineTable, NodeType
from products.endpoints.backend.logic.validation import validate_hogql_query
from products.endpoints.backend.tests.conftest import create_endpoint_with_version
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

CLICKHOUSE = MaterializedViewEngine.CLICKHOUSE
TRINO = MaterializedViewEngine.TRINO
FLAG = "products.endpoints.backend.logic.execution.is_trino_view_copies_enabled"
VALIDATION_FLAG = "products.endpoints.backend.logic.validation.is_trino_view_copies_enabled"


class TestEndpointViewEngine(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.endpoint = create_endpoint_with_version(
            name="orders_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            created_by=self.user,
        )
        self.engines_seen: list[MaterializedViewEngine | None] = []

    def _run(self, *, is_staff: bool, flag: bool, param: str | None) -> list[MaterializedViewEngine | None]:
        self.user.is_staff = is_staff
        self.user.save()

        def run_query(team: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            self.engines_seen.append(create_default_modifiers_for_team(team).materializedViewEngine)
            return {"results": [[1]], "columns": ["id"]}

        url = f"/api/environments/{self.team.id}/endpoints/{self.endpoint.name}/run/"
        if param is not None:
            url += f"?materialized_view_engine={param}"
        with (
            mock.patch(FLAG, return_value=flag),
            mock.patch("products.endpoints.backend.logic.execution.process_query_model", side_effect=run_query),
        ):
            response = self.client.post(url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        return self.engines_seen

    @parameterized.expand(
        [
            ("flag_off", False, False, None, None),
            ("flag_on", False, True, None, TRINO),
            ("customer_param_cannot_turn_trino_on", False, False, "trino", None),
            ("customer_param_cannot_turn_trino_off", False, True, "clickhouse", TRINO),
            ("staff_param_turns_trino_on", True, False, "trino", TRINO),
            ("staff_param_turns_trino_off", True, True, "clickhouse", CLICKHOUSE),
            ("staff_unknown_param_follows_the_flag", True, True, "unknown", TRINO),
            ("staff_without_param_follows_the_flag", True, False, None, None),
        ]
    )
    def test_run_reads_the_engine_the_flag_or_a_staff_param_picks(
        self, _name: str, is_staff: bool, flag: bool, param: str | None, expected: MaterializedViewEngine | None
    ) -> None:
        assert self._run(is_staff=is_staff, flag=flag, param=param) == [expected]

    @parameterized.expand([("flag_on", True, False), ("flag_off", False, True)])
    def test_an_endpoint_can_read_a_raw_trino_view_only_through_its_trino_copy(
        self, _name: str, flag: bool, refused: bool
    ) -> None:
        dag = DAG.get_or_create_default(self.team)
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={
                "query": "SELECT 1 AS id",
                "kind": "HogQLQuery",
                "executionTarget": "managed_trino",
                "sendRawQuery": True,
            },
            columns={"id": "String"},
            is_materialized=True,
        )
        node = Node.objects.create(team=self.team, dag=dag, saved_query=view, type=NodeType.MAT_VIEW)
        NodeEngineTable.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            node=node,
            engine=MaterializationEngine.TRINO,
            table=DataWarehouseTable.objects.create(
                team=self.team,
                name="orders_trino",
                format="Parquet",
                columns={"id": "String"},
                url_pattern="s3://bucket/orders_trino/*.parquet",
            ),
        )

        query = HogQLQuery(query="SELECT id FROM orders")
        with mock.patch(VALIDATION_FLAG, return_value=flag):
            if refused:
                with self.assertRaises(ValidationError):
                    validate_hogql_query(query, self.team, self.user)
            else:
                validate_hogql_query(query, self.team, self.user)
