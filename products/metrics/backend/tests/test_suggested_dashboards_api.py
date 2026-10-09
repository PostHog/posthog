from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.models import (
    MetricsDashboardDiscovery,
    MetricsDashboardSuggestion,
    MetricsDashboardTemplate,
)
from products.metrics.backend.suggested_dashboards.analysis import analyze_team, bank_revision
from products.metrics.backend.suggested_dashboards.discovery import teams_to_analyze
from products.metrics.backend.suggested_dashboards.generation import finish_generation, generation_key
from products.metrics.backend.suggested_dashboards.spec import EvaluationAnswer

QUEUE_METRICS = ["queue_depth", "queue_wait_seconds", "queue_dropped_total", "queue_retries_total"]
CATALOG = [
    CatalogEntry(name="orders_total", metric_type="sum", unit=""),
    CatalogEntry(name="payments_total", metric_type="sum", unit=""),
    *(CatalogEntry(name=name, metric_type="gauge", unit="") for name in QUEUE_METRICS),
]


def _panel(key: str, metric: str, x: int) -> dict[str, Any]:
    return {
        "key": key,
        "title": key.title(),
        "query": {"kind": "MetricsQuery", "clauses": [{"name": "a", "metricName": metric, "aggregation": "rate"}]},
        "layout": {"x": x, "y": 0, "w": 6, "h": 4},
    }


def _template(key: str, status: str, *metrics: str, source: str = "curated") -> MetricsDashboardTemplate:
    return MetricsDashboardTemplate.objects.create(
        key=key,
        name=key.title(),
        source=source,
        status=status,
        panels=[_panel(f"p{index}", metric, 6 * (index % 2)) for index, metric in enumerate(metrics)],
        metric_names=sorted(metrics),
    )


class TestSuggestedDashboardsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.flags = {"metrics", "metrics-suggested-dashboards"}
        self.enterContext(
            patch("posthoganalytics.feature_enabled", side_effect=lambda key, *args, **kwargs: key in self.flags)
        )
        self.enterContext(
            patch.object(MetricCatalog, "load", side_effect=lambda team: MetricCatalog(CATALOG, complete=True))
        )
        self.start_analysis = self.enterContext(patch("products.metrics.backend.temporal.schedule.start_team_analysis"))
        self.orders = _template("orders", "approved", "orders_total", "payments_total")
        self.base_url = f"/api/projects/{self.team.id}/metrics"

    def _answer(self, **values: Any) -> EvaluationAnswer:
        return EvaluationAnswer.model_validate({"suggested": [], "new_dashboards": [], **values})

    @parameterized.expand([("with_ai_consent", True), ("without_ai_consent", False)])
    def test_analysis_suggests_known_templates_and_proposes_uncovered_groups(self, _name: str, consent: bool) -> None:
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        answer = self._answer(
            suggested=[{"key": "orders", "reason": "Order and payment rates"}, {"key": "invented", "reason": "x"}],
            new_dashboards=[
                {"name": "Job queue", "description": "Queue health.", "metric_names": [*QUEUE_METRICS, "made_up"]},
                {"name": "Too small", "description": "x", "metric_names": ["queue_depth"]},
            ],
        )
        with patch(
            "products.metrics.backend.suggested_dashboards.analysis.ask_model", return_value=answer
        ) as ask_model:
            result = analyze_team(self.team.id, force=True)

        suggestions = list(MetricsDashboardSuggestion.objects.for_team(self.team.id).select_related("template"))
        assert [(item.template.key, item.reason) for item in suggestions] == [
            ("orders", "Order and payment rates" if consent else "")
        ]
        assert ask_model.called is consent
        if consent:
            assert [(item.name, item.metric_names) for item in result.generation_requests] == [
                ("Job queue", tuple(sorted(QUEUE_METRICS)))
            ]
        else:
            assert result.generation_requests == ()

    def test_analysis_does_not_propose_a_group_that_the_bank_already_holds(self) -> None:
        _template(generation_key(QUEUE_METRICS), "pending_review", *QUEUE_METRICS, source="generated")
        answer = self._answer(
            new_dashboards=[{"name": "Job queue", "description": "Queue health.", "metric_names": QUEUE_METRICS}]
        )
        with patch("products.metrics.backend.suggested_dashboards.analysis.ask_model", return_value=answer):
            result = analyze_team(self.team.id, force=True)

        assert result.generation_requests == ()

    def test_creating_a_suggested_dashboard_twice_opens_the_same_dashboard(self) -> None:
        template = _template("mixed", "approved", "orders_total", "unknown_total")
        suggestion = MetricsDashboardSuggestion.objects.for_team(self.team.id).create(
            team_id=self.team.id, template=template, coverage=0.5
        )

        listed = self.client.get(f"{self.base_url}/suggested_dashboards/")
        first = self.client.post(f"{self.base_url}/suggested_dashboards/{suggestion.id}/dashboard/")
        second = self.client.post(f"{self.base_url}/suggested_dashboards/{suggestion.id}/dashboard/")

        assert listed.status_code == status.HTTP_200_OK
        assert [item["name"] for item in listed.json()] == ["Mixed"]
        assert first.status_code == status.HTTP_201_CREATED
        assert second.json()["dashboard_id"] == first.json()["dashboard_id"]
        assert DashboardTile.objects.filter(dashboard_id=first.json()["dashboard_id"]).count() == 1

    def test_suggestions_need_the_feature_flag(self) -> None:
        self.flags.discard("metrics-suggested-dashboards")

        response = self.client.get(f"{self.base_url}/suggested_dashboards/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("staff", True, status.HTTP_200_OK), ("not_staff", False, status.HTTP_403_FORBIDDEN)])
    def test_the_template_review_is_for_staff(self, _name: str, is_staff: bool, expected: int) -> None:
        self.user.is_staff = is_staff
        self.user.save(update_fields=["is_staff"])

        response = self.client.get(f"{self.base_url}/dashboard_templates/")

        assert response.status_code == expected

    def test_approving_keeps_the_changes_made_on_the_preview(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        template = _template("generated-queue", "pending_review", *QUEUE_METRICS[:2], source="generated")
        template.source_team_id = self.team.id
        template.save(update_fields=["source_team_id"])

        preview = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/preview/")
        preview_id = preview.json()["dashboard_id"]
        tile = DashboardTile.objects.filter(dashboard_id=preview_id).select_related("insight").first()
        assert tile is not None and tile.insight is not None
        tile.insight.name = "Queue depth now"
        tile.insight.save(update_fields=["name"])
        approved = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/approve/")

        assert approved.status_code == status.HTTP_200_OK
        assert approved.json()["status"] == "approved"
        assert "Queue depth now" in approved.json()["panel_titles"]
        assert Dashboard.objects_including_soft_deleted.get(id=preview_id).deleted
        self.start_analysis.assert_called_once_with(self.team.id, force=True)

    @parameterized.expand(
        [
            ("ready_for_review", ["queue_depth"], "pending_review", None),
            ("no_panel_passed", [], "failed", "No drafted panel passed the query checks."),
        ]
    )
    def test_finishing_a_generation_sends_one_event_with_the_review_link(
        self, _name: str, metrics: list[str], expected_status: str, expected_error: str | None
    ) -> None:
        template = _template("generated-queue", "generating", *metrics, source="generated")
        template.source_team_id = self.team.id
        template.save(update_fields=["source_team_id"])

        with patch("products.metrics.backend.suggested_dashboards.generation.ph_background_capture") as background:
            finish_generation(str(template.id))

        background.return_value.assert_called_once()
        event = background.return_value.call_args.kwargs
        assert event["event"] == "metrics dashboard generated"
        assert (event["properties"]["status"], event["properties"]["error"]) == (expected_status, expected_error)
        assert event["properties"]["review_url"].endswith(f"/metrics/dashboard-review/{template.id}")
        assert event["groups"]["project"] == str(self.team.uuid)

    def test_a_curated_template_cannot_be_rejected(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.post(f"{self.base_url}/dashboard_templates/{self.orders.id}/reject/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_discovery_picks_only_teams_whose_names_or_bank_changed(self) -> None:
        unchanged = Team.objects.create(organization=self.organization, name="Unchanged")
        MetricsDashboardDiscovery.objects.for_team(unchanged.id).create(
            team_id=unchanged.id, names_fingerprint=7, bank_revision=bank_revision()
        )
        with patch(
            "products.metrics.backend.suggested_dashboards.discovery.name_fingerprints",
            return_value={self.team.id: 5, unchanged.id: 7},
        ):
            picked = teams_to_analyze()

        assert picked == [self.team.id]
        state = MetricsDashboardDiscovery.objects.for_team(self.team.id).get()
        assert state.names_fingerprint == 5

    def test_listing_suggestions_starts_the_first_analysis_of_a_team(self) -> None:
        self.client.get(f"{self.base_url}/suggested_dashboards/")
        MetricsDashboardDiscovery.objects.for_team(self.team.id).create(team_id=self.team.id, analyzed_at="2026-01-01")
        self.client.get(f"{self.base_url}/suggested_dashboards/")

        assert isinstance(self.start_analysis, MagicMock)
        self.start_analysis.assert_called_once_with(self.team.id, force=True)
