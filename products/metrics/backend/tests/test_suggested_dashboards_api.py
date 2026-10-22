import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import MetricsDashboardVariable

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
from products.metrics.backend.suggested_dashboards.bank import sync_curated_templates
from products.metrics.backend.suggested_dashboards.dashboards import attribute_variable
from products.metrics.backend.suggested_dashboards.discovery import record_opened, teams_to_analyze
from products.metrics.backend.suggested_dashboards.generation import (
    fail_stale_generations,
    finish_generation,
    generation_key,
)
from products.metrics.backend.suggested_dashboards.review import SuggestionGone, create_from_suggestion
from products.metrics.backend.suggested_dashboards.spec import EvaluationAnswer
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables
from products.metrics.backend.variable_options import list_variable_options

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


def _with_variable_filter(panel: dict[str, Any], name: str) -> dict[str, Any]:
    panel["query"]["clauses"][0]["filters"] = [{"key": name, "op": "eq", "value": f"${name}"}]
    return panel


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

        Dashboard.objects.filter(id=first.json()["dashboard_id"]).update(deleted=True)
        relisted = self.client.get(f"{self.base_url}/suggested_dashboards/")
        recreated = self.client.post(f"{self.base_url}/suggested_dashboards/{suggestion.id}/dashboard/")

        assert relisted.json()[0]["dashboard_id"] is None
        assert recreated.status_code == status.HTTP_201_CREATED
        assert recreated.json()["dashboard_id"] not in (None, first.json()["dashboard_id"])

    def test_a_suggested_dashboard_gets_the_variables_of_its_tiles(self) -> None:
        template = _template("mixed", "approved", "orders_total", "unknown_total")
        _with_variable_filter(template.panels[0], "instance")
        # The project does not send unknown_total, so its panel and its variable stay out.
        _with_variable_filter(template.panels[1], "job")
        template.variables = [
            attribute_variable(name="instance", label="Instance", attribute="instance"),
            attribute_variable(name="job", label="Job", attribute="job"),
        ]
        template.save(update_fields=["panels", "variables"])
        suggestion = MetricsDashboardSuggestion.objects.for_team(self.team.id).create(
            team_id=self.team.id, template=template, coverage=0.5
        )

        response = self.client.post(f"{self.base_url}/suggested_dashboards/{suggestion.id}/dashboard/")

        assert response.status_code == status.HTTP_201_CREATED
        dashboard = Dashboard.objects.get(id=response.json()["dashboard_id"])
        assert dashboard.filters["metricVariables"] == [template.variables[0]]
        assert dashboard.filters["metricVariables"][0]["current"] == {"values": [], "all": True}

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
        # This project does not send unknown_total, so the preview leaves P2 out.
        template = _template(
            "generated-queue", "pending_review", *QUEUE_METRICS[:2], "unknown_total", source="generated"
        )
        # One row of three. The preview must not widen the others into the gap of P2.
        for index, panel in enumerate(template.panels):
            panel["layout"].update(x=4 * index, w=4)
        template.source_team_id = self.team.id
        template.save(update_fields=["source_team_id", "panels"])

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
        template.refresh_from_db()
        assert [(panel["title"], panel["layout"]["x"], panel["layout"]["y"]) for panel in template.panels] == [
            ("Queue depth now", 0, 0),
            ("P1", 4, 0),
            ("P2", 8, 0),
        ]
        assert Dashboard.objects_including_soft_deleted.get(id=preview_id).deleted
        self.start_analysis.assert_called_once_with(self.team.id, force=True)

    def test_approving_keeps_the_variables_of_the_preview_and_of_the_panels_it_left_out(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        template = _template("generated-queue", "pending_review", "queue_depth", "unknown_total", source="generated")
        _with_variable_filter(template.panels[0], "instance")
        _with_variable_filter(template.panels[1], "job")
        template.variables = [
            attribute_variable(name="instance", label="Instance", attribute="instance"),
            attribute_variable(name="job", label="Job", attribute="job"),
        ]
        template.source_team_id = self.team.id
        template.save(update_fields=["panels", "variables", "source_team_id"])

        preview = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/preview/")
        dashboard = Dashboard.objects.get(id=preview.json()["dashboard_id"])
        assert [variable["name"] for variable in dashboard.filters["metricVariables"]] == ["instance"]
        # The reviewer renames the variable and selects an instance of this project, which other projects must not see.
        edited = {
            **attribute_variable(name="instance", label="Host", attribute="instance"),
            "current": {"values": ["web-1"]},
        }
        dashboard.filters = {**dashboard.filters, "metricVariables": [edited]}
        dashboard.save(update_fields=["filters"])
        approved = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/approve/")

        assert approved.status_code == status.HTTP_200_OK
        template.refresh_from_db()
        assert template.variables == [
            attribute_variable(name="instance", label="Host", attribute="instance"),
            attribute_variable(name="job", label="Job", attribute="job"),
        ]

    @parameterized.expand(
        [
            ("does_not_parse", {"name": "instance", "source": "invented"}),
            (
                "lists_values_of_the_preview_project",
                {"name": "instance", "source": "custom", "customValues": ["web-1", "web-2"], "includeAll": True},
            ),
        ]
    )
    def test_approving_ignores_a_preview_variable_that_cannot_be_shared(
        self, _name: str, preview_variable: dict[str, Any]
    ) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        template = _template("generated-queue", "pending_review", "queue_depth", source="generated")
        _with_variable_filter(template.panels[0], "instance")
        template.variables = [attribute_variable(name="instance", label="Instance", attribute="instance")]
        template.source_team_id = self.team.id
        template.save(update_fields=["panels", "variables", "source_team_id"])

        preview = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/preview/")
        dashboard = Dashboard.objects.get(id=preview.json()["dashboard_id"])
        dashboard.filters = {**dashboard.filters, "metricVariables": [preview_variable]}
        dashboard.save(update_fields=["filters"])
        approved = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/approve/")

        assert approved.status_code == status.HTTP_200_OK
        template.refresh_from_db()
        # The template keeps its own definition.
        assert template.variables == [attribute_variable(name="instance", label="Instance", attribute="instance")]

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
        template.metric_names = [*metrics, "queue_requested_total"]
        template.save(update_fields=["source_team_id", "metric_names"])

        with patch("products.metrics.backend.suggested_dashboards.generation.ph_background_capture") as background:
            finish_generation(str(template.id))

        background.return_value.assert_called_once()
        event = background.return_value.call_args.kwargs
        assert event["event"] == "metrics dashboard generated"
        assert (event["properties"]["status"], event["properties"]["error"]) == (expected_status, expected_error)
        assert event["properties"]["review_url"].endswith(f"/metrics/dashboard-review/{template.id}")
        assert event["groups"]["project"] == str(self.team.uuid)
        template.refresh_from_db()
        assert template.status == expected_status
        # A finished template lists only the metrics of its panels. A failed one keeps the request.
        assert template.metric_names == (metrics or ["queue_requested_total"])

    @parameterized.expand(
        [
            ("rejecting_a_curated_one", "reject", "approved", "curated"),
            ("rejecting_one_still_generating", "reject", "generating", "generated"),
            ("approving_a_withdrawn_curated_one", "approve", "rejected", "curated"),
            ("regenerating_a_curated_one", "regenerate", "rejected", "curated"),
            ("regenerating_one_still_generating", "regenerate", "generating", "generated"),
            ("regenerating_an_approved_one", "regenerate", "approved", "generated"),
        ]
    )
    def test_a_template_that_cannot_be_reviewed(
        self, _name: str, action: str, template_status: str, source: str
    ) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        template = _template(f"review-{_name}", template_status, "orders_total", source=source)

        response = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/{action}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        template.refresh_from_db()
        assert template.status == template_status

    @parameterized.expand(
        [
            ("started", None, None, 200, "generating"),
            ("not_started", RuntimeError, False, 400, "failed"),
            ("started_but_the_answer_was_lost", RuntimeError, True, 200, "generating"),
            ("unknown", RuntimeError, None, 400, "generating"),
        ]
    )
    def test_regenerating_discards_the_panels_and_starts_again_from_the_requested_metrics(
        self,
        _name: str,
        start_error: type[Exception] | None,
        running: bool | None,
        expected_code: int,
        expected_status: str,
    ) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        preview = Dashboard.objects.create(
            team=self.team, name="Preview", creation_mode=Dashboard.CreationMode.UNLISTED
        )
        template = _template("generated-queue", "rejected", "queue_depth", source="generated")
        template.source_team_id = self.team.id
        template.preview_team_id, template.preview_dashboard_id = self.team.id, preview.id
        template.generation = {"requested_name": "Job queue", "requested_metric_names": QUEUE_METRICS}
        template.save()

        with (
            patch("products.metrics.backend.temporal.schedule.start_regeneration", side_effect=start_error) as start,
            patch(
                "products.metrics.backend.temporal.schedule.generation_running",
                side_effect=lambda key, started_after=None: running if started_after else False,
            ),
            patch("products.metrics.backend.suggested_dashboards.generation.ph_background_capture"),
        ):
            response = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/regenerate/")

        assert response.status_code == expected_code
        start.assert_called_once()
        team_id, template_id, request = start.call_args.args
        assert (team_id, template_id, request.key, request.metric_names) == (
            self.team.id,
            str(template.id),
            "generated-queue",
            QUEUE_METRICS,
        )
        saved = MetricsDashboardTemplate.objects.get(id=template.id)
        assert (saved.status, saved.panels, saved.name) == (expected_status, [], "Job queue")
        assert saved.preview_dashboard_id is None
        assert not Dashboard.objects.filter(id=preview.id, deleted=False).exists()

    def test_regenerating_waits_for_the_previous_run_to_close(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        template = _template("generated-queue", "pending_review", "queue_depth", source="generated")
        template.source_team_id = self.team.id
        template.save(update_fields=["source_team_id"])

        with (
            patch("products.metrics.backend.temporal.schedule.generation_running", return_value=True),
            patch("products.metrics.backend.temporal.schedule.start_regeneration") as start,
        ):
            response = self.client.post(f"{self.base_url}/dashboard_templates/{template.id}/regenerate/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        start.assert_not_called()
        template.refresh_from_db()
        assert (template.status, len(template.panels)) == ("pending_review", 1)

    def test_a_curated_template_comes_back_with_its_file(self) -> None:
        sync_curated_templates()
        # An older worker without the file withdrew it during a deploy.
        MetricsDashboardTemplate.objects.filter(key="redis").update(status="rejected")

        sync_curated_templates()

        assert MetricsDashboardTemplate.objects.get(key="redis").status == "approved"

    def test_the_sweep_fails_a_generation_that_stopped(self) -> None:
        preview = Dashboard.objects.create(
            team=self.team, name="Preview", creation_mode=Dashboard.CreationMode.UNLISTED
        )
        broken = _template("generated-broken", "generating", "queue_depth", source="generated")
        stopped = _template("generated-stopped", "generating", "queue_depth", source="generated")
        running = _template("generated-running", "generating", "queue_depth", source="generated")
        MetricsDashboardTemplate.objects.filter(id=broken.id).update(generation={"rounds": "not a list"})
        MetricsDashboardTemplate.objects.filter(id=stopped.id).update(
            preview_team_id=self.team.id, preview_dashboard_id=preview.id
        )
        MetricsDashboardTemplate.objects.filter(id__in=[broken.id, stopped.id]).update(
            updated_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
        )

        with patch("products.metrics.backend.suggested_dashboards.generation.ph_background_capture") as background:
            fail_stale_generations(dt.datetime.now(dt.UTC))
            # The workflow's own finish arrives late. The sweep's verdict stays.
            finish_generation(str(stopped.id))

        broken.refresh_from_db()
        stopped.refresh_from_db()
        running.refresh_from_db()
        assert (broken.status, stopped.status, running.status) == ("failed", "failed", "generating")
        assert background.return_value.call_count == 1
        assert stopped.preview_dashboard_id is None
        assert Dashboard.objects_including_soft_deleted.get(id=preview.id).deleted

    def test_creating_from_a_suggestion_that_was_removed_returns_not_found(self) -> None:
        suggestion = MetricsDashboardSuggestion.objects.for_team(self.team.id).create(
            team_id=self.team.id, template=self.orders, coverage=1.0
        )
        loaded = (
            MetricsDashboardSuggestion.objects.for_team(self.team.id).select_related("template").get(id=suggestion.id)
        )
        suggestion.delete()

        with self.assertRaises(SuggestionGone):
            create_from_suggestion(suggestion=loaded, team=self.team, user=self.user)

    @parameterized.expand([("flag_on", True), ("flag_off_after_suggestions_were_opened", False)])
    def test_discovery_picks_only_teams_whose_names_or_bank_changed(self, _name: str, flag_on: bool) -> None:
        if not flag_on:
            # The flag can target people, so a team whose user opened its suggestions stays analyzed.
            self.flags.discard("metrics-suggested-dashboards")
            record_opened(self.team.id)
        unchanged = Team.objects.create(organization=self.organization, name="Unchanged")
        MetricsDashboardDiscovery.objects.for_team(unchanged.id).create(
            team_id=unchanged.id, names_fingerprint=7, bank_revision=bank_revision()
        )
        with patch(
            "products.metrics.backend.suggested_dashboards.discovery.name_fingerprints",
            return_value={self.team.id: 5, unchanged.id: 7},
        ):
            picked = teams_to_analyze()

        assert picked == {self.team.id: 5}
        # The analysis records the fingerprint, so a team whose analysis fails is picked again, but not at once.
        assert not MetricsDashboardDiscovery.objects.for_team(self.team.id).filter(names_fingerprint=5).exists()
        with (
            patch("products.metrics.backend.suggested_dashboards.analysis.ask_model", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            analyze_team(self.team.id, names_fingerprint=5)
        with patch(
            "products.metrics.backend.suggested_dashboards.discovery.name_fingerprints",
            return_value={self.team.id: 5, unchanged.id: 7},
        ):
            assert teams_to_analyze() == {}
        with patch("products.metrics.backend.suggested_dashboards.analysis.ask_model", return_value=self._answer()):
            analyze_team(self.team.id, names_fingerprint=5)
        assert MetricsDashboardDiscovery.objects.for_team(self.team.id).get().names_fingerprint == 5

    def test_analysis_matches_template_metrics_beyond_the_catalog_limit(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        truncated = MetricCatalog([CatalogEntry(name="other_total", metric_type="sum", unit="")], complete=False)

        def names_runner(*args: Any, names: list[str], **kwargs: Any) -> MagicMock:
            return MagicMock(run=lambda: [{"name": name, "metric_type": "sum", "unit": ""} for name in names])

        with (
            patch.object(MetricCatalog, "load", return_value=truncated),
            patch("products.metrics.backend.dashboard_import.catalog.MetricNamesQueryRunner", side_effect=names_runner),
        ):
            analyze_team(self.team.id, force=True)

        suggestions = MetricsDashboardSuggestion.objects.for_team(self.team.id).select_related("template")
        assert [suggestion.template.key for suggestion in suggestions] == ["orders"]

    def test_a_template_that_waits_for_no_review_gets_no_preview(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        revision = bank_revision()

        preview = self.client.post(f"{self.base_url}/dashboard_templates/{self.orders.id}/preview/")

        # No review would ever delete it, so it would stay in the reviewer's project.
        assert preview.status_code == status.HTTP_400_BAD_REQUEST
        assert not Dashboard.objects.filter(team=self.team).exists()
        assert bank_revision() == revision

    def test_opening_suggestions_analyzes_changes_that_the_sweep_only_noted(self) -> None:
        MetricsDashboardDiscovery.objects.for_team(self.team.id).create(
            team_id=self.team.id, names_fingerprint=1, analyzed_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
        )
        # The flag check misses the team, so the sweep only notes its new names.
        self.flags.discard("metrics-suggested-dashboards")
        with patch(
            "products.metrics.backend.suggested_dashboards.discovery.name_fingerprints",
            return_value={self.team.id: 2},
        ):
            assert teams_to_analyze() == {}
        self.flags.add("metrics-suggested-dashboards")

        self.client.get(f"{self.base_url}/suggested_dashboards/")

        self.start_analysis.assert_called_once_with(self.team.id, force=True)

    def test_listing_suggestions_starts_the_first_analysis_of_a_team(self) -> None:
        # The first start fails, so the next list tries again. After a start, more lists do not start another.
        self.start_analysis.side_effect = [RuntimeError("Temporal is unavailable"), None]
        self.client.get(f"{self.base_url}/suggested_dashboards/")
        self.client.get(f"{self.base_url}/suggested_dashboards/")
        self.client.get(f"{self.base_url}/suggested_dashboards/")
        MetricsDashboardDiscovery.objects.for_team(self.team.id).create(
            team_id=self.team.id, analyzed_at=dt.datetime.now(dt.UTC)
        )
        self.client.get(f"{self.base_url}/suggested_dashboards/")

        assert isinstance(self.start_analysis, MagicMock)
        assert self.start_analysis.call_count == 2
        self.start_analysis.assert_called_with(self.team.id, force=True)


class TestSuggestedDashboardVariableOptions(ClickhouseTestMixin, APIBaseTest):
    def test_options_list_the_values_of_the_hour_that_holds_the_start_of_the_range(self) -> None:
        truncate_metrics_tables()
        # A range that starts after the hour still finds the samples in the bucket of that hour.
        start = dt.datetime.now(dt.UTC).replace(minute=20, second=0, microsecond=0) - dt.timedelta(hours=2)
        seed_metric(
            team_id=self.team.id,
            metric_name="queue_depth",
            service_name="checkout",
            points=[(start + dt.timedelta(minutes=5), 1.0)],
            labels={"instance": "web-1"},
        )
        later = start + dt.timedelta(hours=1, minutes=10)
        seed_metric(
            team_id=self.team.id,
            metric_name="queue_depth",
            service_name="billing",
            points=[(later, 1.0)],
            labels={"instance": "web-2"},
        )

        def options(attribute: str) -> list[str]:
            definition = MetricsDashboardVariable.model_validate(
                attribute_variable(name="scope", label="Scope", attribute=attribute)
            )
            return list_variable_options(
                team=self.team,
                source=definition.source,
                query=definition.query,
                custom_values=None,
                variables={},
                date_from=start,
                date_to=start + dt.timedelta(minutes=30),
            )

        assert options("instance") == ["web-1"]
        assert options("service_name") == ["checkout"]
