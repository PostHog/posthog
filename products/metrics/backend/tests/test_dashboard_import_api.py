import io
import json
import base64
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from PIL import Image
from rest_framework import status

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.models import User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.importer import AGENT_MCP_SCOPES, IMPORT_STATE_KEY
from products.metrics.backend.facade.api import finalize_dashboard_import
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries
from products.tasks.backend.models import Task, TaskRun

IMPORTER = "products.metrics.backend.dashboard_import.importer"
WORKFLOW = "products.tasks.backend.temporal.client.execute_task_processing_workflow"
CATALOG = [
    CatalogEntry(name="orders_total", metric_type="sum", unit=""),
    CatalogEntry(name="checkout.duration", metric_type="histogram", unit="s"),
]


def _grafana(*exprs: str) -> str:
    panels: list[dict[str, Any]] = [
        {"id": 1, "type": "row", "title": "Orders", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}}
    ]
    for index, expr in enumerate(exprs, start=2):
        panels.append(
            {
                "id": index,
                "type": "timeseries",
                "title": f"Panel {index}",
                "gridPos": {"x": 0, "y": index * 8, "w": 12, "h": 8},
                "datasource": {"type": "prometheus", "uid": "prom"},
                "targets": [{"refId": "A", "expr": expr}],
            }
        )
    return json.dumps({"title": "Orders", "time": {"from": "now-6h"}, "panels": panels})


def _png() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), color=(30, 30, 30)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class TestDashboardImportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/metrics/dashboard_imports/"
        self.flags = {"metrics", "metrics-dashboard-import", SNUFFLE_API_FEATURE_FLAG}
        self.enterContext(
            patch("posthoganalytics.feature_enabled", side_effect=lambda key, *args, **kwargs: key in self.flags)
        )
        self.enterContext(override_settings(SNUFFLE_APM_URL="http://snuffle.test"))
        self.workflow = self.enterContext(patch(WORKFLOW))
        self.storage = self.enterContext(patch(f"{IMPORTER}.object_storage"))
        self.enterContext(
            patch(f"{IMPORTER}.MetricCatalog.load", side_effect=lambda team: MetricCatalog(CATALOG, complete=True))
        )
        self.smoke_run = self.enterContext(
            patch(
                "products.metrics.backend.dashboard_import.validation.run_promql_range",
                return_value=[MetricSeries(labels={}, points=(MetricPoint(time="2026-10-08T10:00:00Z", value=2.0),))],
            )
        )

    def _start(self, **body: Any) -> dict[str, Any]:
        response = self.client.post(self.url, body, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _finish_run(self, import_id: str, *, run_status: str, output: dict[str, Any] | None) -> None:
        run = TaskRun.objects.get(task_id=import_id)
        run.status = run_status
        run.output = output
        with (
            patch(
                "products.metrics.backend.tasks.tasks.finalize_metrics_dashboard_import.delay",
                side_effect=lambda team_id, task_id: finalize_dashboard_import(team_id=team_id, import_id=task_id),
            ) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            run.save(update_fields=["status", "output"])
        delay.assert_called_once_with(self.team.id, import_id)

    def test_imports_matching_panels_at_once_without_an_agent(self) -> None:
        body = self._start(source="grafana", grafana_json=_grafana("sum(rate(orders_total[$__rate_interval]))"))

        assert (body["id"], body["status"], body["error"]) == (None, "completed", None)
        assert body["summary"] == {"total": 2, "imported": 2, "approximated": 0, "failed": 0, "skipped": 0}
        dashboard = Dashboard.objects.get(id=body["dashboard_id"])
        assert (dashboard.name, dashboard.filters) == ("Orders", {"date_from": "-6h"})
        tiles = sorted(DashboardTile.objects.filter(dashboard=dashboard), key=lambda tile: tile.layouts["sm"]["y"])
        assert tiles[0].text is not None and tiles[0].text.body == "## Orders"
        assert tiles[1].insight is not None and tiles[1].insight.query == {
            "kind": "MetricsQuery",
            "language": "promql",
            "promql": "sum(rate(orders_total))",
            "clauses": [],
            "display": {"type": "line"},
        }
        assert tiles[1].layouts == {"sm": {"x": 0, "y": 1, "w": 6, "h": 3}}
        self.workflow.assert_not_called()

    def test_starts_a_read_only_agent_for_panels_it_cannot_match(self) -> None:
        body = self._start(
            source="grafana",
            grafana_json=_grafana("sum(rate(orders_total[5m]))", "sum(rate(payments_total[5m]))"),
        )

        assert (body["status"], body["dashboard_id"]) == ("running", None)
        task = Task.objects.get(id=body["id"])
        run = TaskRun.objects.get(task=task)
        assert (task.origin_product, task.internal, task.repository) == (Task.OriginProduct.METRICS_IMPORT, True, None)
        assert run.state["pending_dispatch"]["posthog_mcp_scopes"] == AGENT_MCP_SCOPES
        assert "docs-search" in run.state["mcp_exclude_tools"]
        assert {artifact["name"] for artifact in run.artifacts} == {"brief.json", "grafana-dashboard.json"}
        assert run.state["pending_user_artifact_ids"] == [artifact["id"] for artifact in run.artifacts]
        brief = json.loads(self.storage.write.call_args_list[0].args[1])
        assert [panel["key"] for panel in brief["panels_to_convert"]] == ["p3"]
        assert (
            "These metrics do not exist in this project: payments_total."
            in brief["panels_to_convert"][0]["check_error"]
        )
        assert [verdict["key"] for verdict in (task.state or {})[IMPORT_STATE_KEY]["resolved"]] == ["p1", "p2"]

    def test_builds_the_dashboard_once_from_the_agent_answer(self) -> None:
        started = self._start(
            source="grafana",
            grafana_json=_grafana("sum(rate(orders_total[5m]))", "rate(payments_total[5m])", "rate(refunds_total[5m])"),
        )
        answer = {
            "dashboard_name": "Orders",
            "panels": [
                {
                    "key": "p3",
                    "title": "Payments",
                    "outcome": "approximated",
                    "reason": "Uses orders_total because the project has no payments metric.",
                    "query": {"language": "promql", "promql": "sum(rate(orders_total))"},
                },
                {
                    "key": "p4",
                    "title": "Refunds",
                    "outcome": "imported",
                    "reason": "",
                    "query": {"language": "promql", "promql": "rate(refunds_total)"},
                },
            ],
        }

        self._finish_run(started["id"], run_status=TaskRun.Status.COMPLETED, output=answer)
        first = self.client.get(f"{self.url}{started['id']}/").json()
        second = self.client.get(f"{self.url}{started['id']}/").json()

        assert first["status"] == "completed"
        assert first["summary"] == {"total": 4, "imported": 2, "approximated": 1, "failed": 1, "skipped": 0}
        assert [(panel["key"], panel["outcome"]) for panel in first["panels"]] == [
            ("p1", "imported"),
            ("p2", "imported"),
            ("p3", "approximated"),
            ("p4", "failed"),
        ]
        assert "refunds_total" in first["panels"][3]["reason"]
        assert second["dashboard_id"] == first["dashboard_id"]
        assert Dashboard.objects.filter(team=self.team).count() == 1
        assert DashboardTile.objects.filter(dashboard_id=first["dashboard_id"]).count() == 3
        self.storage.delete.assert_called()

    @parameterized.expand(
        [
            ("run_failed", TaskRun.Status.FAILED, None, "stopped before it finished"),
            ("unreadable_answer", TaskRun.Status.COMPLETED, {"panels": "none"}, "cannot read"),
        ]
    )
    def test_a_failed_agent_run_creates_no_dashboard(
        self, _name: str, run_status: str, output: dict[str, Any] | None, error: str
    ) -> None:
        started = self._start(source="grafana", grafana_json=_grafana("rate(payments_total[5m])"))

        self._finish_run(started["id"], run_status=run_status, output=output)
        body = self.client.get(f"{self.url}{started['id']}/").json()

        assert (body["status"], body["dashboard_id"]) == ("failed", None)
        assert error in body["error"]
        assert not Dashboard.objects.filter(team=self.team).exists()

    def test_screenshot_import_places_the_panels_that_the_agent_read(self) -> None:
        started = self._start(source="screenshot", image_base64=_png())
        run = TaskRun.objects.get(task_id=started["id"])
        assert {artifact["name"] for artifact in run.artifacts} == {"brief.json", "screenshot.png"}

        self._finish_run(
            started["id"],
            run_status=TaskRun.Status.COMPLETED,
            output={
                "dashboard_name": "Checkout",
                "panels": [
                    {
                        "key": "s1",
                        "title": "Latency",
                        "outcome": "imported",
                        "reason": "",
                        "query": {"language": "histogram", "histogram_metric": "checkout.duration"},
                        "display": {"type": "heatmap", "unit": "s"},
                        "layout": {"x": 0, "y": 0, "w": 8, "h": 4},
                    },
                    {
                        "key": "s2",
                        "title": "Orders",
                        "outcome": "imported",
                        "reason": "",
                        "query": {"language": "promql", "promql": "sum(rate(orders_total))"},
                        "display": {"type": "stat"},
                        "layout": {"x": 6, "y": 0, "w": 6, "h": 2},
                    },
                ],
            },
        )
        body = self.client.get(f"{self.url}{started['id']}/").json()

        assert body["status"] == "completed", body
        tiles = {
            tile.insight.name: (tile.insight.query, tile.layouts["sm"])
            for tile in DashboardTile.objects.filter(dashboard_id=body["dashboard_id"])
            if tile.insight is not None
        }
        assert tiles["Latency"] == (
            {
                "kind": "MetricsHistogramQuery",
                "metricName": "checkout.duration",
                "metricType": "histogram",
                "unit": "s",
            },
            {"x": 0, "y": 0, "w": 8, "h": 4},
        )
        # The agent overlapped the two boxes, so the second one moves below the first.
        assert tiles["Orders"][1] == {"x": 6, "y": 4, "w": 6, "h": 2}

    @parameterized.expand(
        [
            (
                "import_flag_off",
                {"source": "grafana", "grafana_json": _grafana("up")},
                status.HTTP_403_FORBIDDEN,
                "flag",
            ),
            (
                "ai_processing_off",
                {"source": "grafana", "grafana_json": _grafana("up")},
                status.HTTP_403_FORBIDDEN,
                "ai",
            ),
            ("not_json", {"source": "grafana", "grafana_json": "{panels"}, status.HTTP_400_BAD_REQUEST, None),
            ("not_an_image", {"source": "screenshot", "image_base64": "aGVsbG8="}, status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_refuses_imports_it_cannot_run(
        self, _name: str, body: dict[str, Any], expected_status: int, switch: str | None
    ) -> None:
        if switch == "flag":
            self.flags.discard("metrics-dashboard-import")
        if switch == "ai":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])

        response = self.client.post(self.url, body, format="json")

        assert response.status_code == expected_status, response.json()
        assert not Dashboard.objects.filter(team=self.team).exists()
        assert not Task.objects.filter(team=self.team).exists()

    def test_one_running_import_per_user(self) -> None:
        self._start(source="grafana", grafana_json=_grafana("rate(payments_total[5m])"))

        response = self.client.post(
            self.url, {"source": "grafana", "grafana_json": _grafana("rate(refunds_total[5m])")}, format="json"
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert Task.objects.filter(team=self.team).count() == 1
        self.storage.delete.assert_called()

    def test_validate_reports_what_to_fix_for_each_panel(self) -> None:
        response = self.client.post(
            f"{self.url}validate/",
            {
                "panels": [
                    {"key": "ok", "language": "promql", "promql": "sum(rate(orders_total))"},
                    {"key": "unknown", "language": "promql", "promql": "rate(payments_total)"},
                    {"key": "sql", "language": "hogql", "hogql": "SELECT count() FROM logs"},
                    {
                        "key": "histogram",
                        "language": "builder",
                        "builder": {
                            "clauses": [
                                {"name": "a", "metric_name": "orders_total", "aggregation": "histogram_quantile"}
                            ]
                        },
                    },
                    {
                        "key": "p95",
                        "language": "builder",
                        "builder": {"clauses": [{"name": "a", "metric_name": "orders_total", "aggregation": "p95"}]},
                    },
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = {item["key"]: item for item in response.json()["results"]}
        assert results["ok"]["valid"] is True
        assert "payments_total" in results["unknown"]["error"]
        assert "{filters}" in results["sql"]["error"]
        assert "quantile" in results["histogram"]["error"]
        assert results["p95"]["valid"] is True

    def test_status_of_another_users_import_is_not_found(self) -> None:
        started = self._start(source="grafana", grafana_json=_grafana("rate(payments_total[5m])"))
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        Task.objects.filter(id=started["id"]).update(created_by=other)

        response = self.client.get(f"{self.url}{started['id']}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
