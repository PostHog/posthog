from typing import Any

from posthog.test.base import TestMigrations

PROMQL = {"kind": "MetricsQuery", "clauses": [], "language": "promql", "promql": 'up{job=~"$job"}'}
JOB_VALUES = {"job": {"values": ["api"], "allValue": ".+"}}
CUSTOM_ALL = {"job": {"values": [], "all": True, "allValue": ".+"}}
HOGQL = {
    "kind": "DataVisualizationNode",
    "source": {"kind": "HogQLQuery", "query": "select {variables.v}", "variables": {"v": {"code_name": "v"}}},
}


class TestRemoveMetricsInsightVariableValues(TestMigrations):
    app = "product_analytics"
    migrate_from = "0013_squash_2026_11_02_schema_addons"
    migrate_to = "0014_remove_metrics_insight_variable_values"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Insight = apps.get_model("product_analytics", "Insight")
        AlertConfiguration = apps.get_model("alerts", "AlertConfiguration")

        metrics = Insight.objects.create(team_id=self.team.id, query={**PROMQL, "variables": JOB_VALUES})
        self.metrics_insight = metrics.id
        self.hogql_insight = Insight.objects.create(team_id=self.team.id, query=HOGQL).id
        self.alert = AlertConfiguration.objects.create(
            team_id=self.team.id, insight=metrics, config={"type": "MetricsAlertConfig"}
        ).id
        self.alert_with_values = AlertConfiguration.objects.create(
            team_id=self.team.id,
            insight=metrics,
            config={"type": "MetricsAlertConfig", "variables": {"job": {"values": ["worker"]}}},
        ).id

        custom_all = Insight.objects.create(team_id=self.team.id, query={**PROMQL, "variables": CUSTOM_ALL})
        self.custom_all_insight = custom_all.id
        self.custom_all_alert = AlertConfiguration.objects.create(
            team_id=self.team.id, insight=custom_all, config={"type": "MetricsAlertConfig"}
        ).id
        self.custom_all_without_alerts = Insight.objects.create(
            team_id=self.team.id, query={**PROMQL, "variables": CUSTOM_ALL}
        ).id

    def test_moves_values_from_metrics_insights_to_their_alerts(self) -> None:
        Insight = self.apps.get_model("product_analytics", "Insight")  # type: ignore[union-attr]
        AlertConfiguration = self.apps.get_model("alerts", "AlertConfiguration")  # type: ignore[union-attr]

        assert Insight.objects.get(id=self.metrics_insight).query == PROMQL
        assert Insight.objects.get(id=self.hogql_insight).query == HOGQL
        assert AlertConfiguration.objects.get(id=self.alert).config == {
            "type": "MetricsAlertConfig",
            "variables": {"job": {"values": ["api"]}},
        }
        assert AlertConfiguration.objects.get(id=self.alert_with_values).config["variables"] == {
            "job": {"values": ["worker"]}
        }

        # An alert cannot hold a custom All, so the insight keeps it and the alert stays as it was.
        assert Insight.objects.get(id=self.custom_all_insight).query == {**PROMQL, "variables": CUSTOM_ALL}
        assert AlertConfiguration.objects.get(id=self.custom_all_alert).config == {"type": "MetricsAlertConfig"}
        assert Insight.objects.get(id=self.custom_all_without_alerts).query == PROMQL
