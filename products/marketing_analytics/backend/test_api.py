from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.hogql import ast

from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class FakeMarketingAdapter:
    def __init__(self, *args, **kwargs):
        pass

    def _build_select_columns(self) -> list[ast.Expr]:
        return [ast.Constant(value=1)]

    def _get_from(self) -> ast.JoinExpr:
        return ast.JoinExpr(table=ast.Field(chain=["sample_marketing_table"]))

    def _get_where_conditions(self) -> list[ast.Expr]:
        return []


class TestMarketingAnalyticsAPI(APIBaseTest):
    @patch("products.marketing_analytics.backend.api._get_adapter_class", return_value=FakeMarketingAdapter)
    @patch("products.marketing_analytics.backend.api.execute_hogql_query")
    def test_mapping_passes_request_user_to_hogql_query(self, mock_execute_hogql_query, _mock_get_adapter_class):
        table = DataWarehouseTable.objects.create(
            name="sample_marketing_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="s3://bucket/sample_marketing_table",
            columns={"campaign": "String"},
        )
        mock_execute_hogql_query.return_value = SimpleNamespace(results=[[1]], columns=["one"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/marketing_analytics/test_mapping/",
            {"table_id": str(table.id), "source_map": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_execute_hogql_query.call_args.kwargs["user"], self.user)
