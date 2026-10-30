from datetime import datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.dashboard_widgets import (
    experiment_results_widget,
    experiments_list_widget_page,
    has_accessible_experiments,
)
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_GROUP_KEY,
    Experiment,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

RUNNER = "products.experiments.backend.dashboard_widgets.ExperimentQueryRunner"
MAX_METRICS = 3


def _metric(uuid: str, name: str) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": uuid,
        "name": name,
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }


class TestDashboardWidgetsFacade(BaseTest):
    def _experiment(
        self,
        name: str,
        *,
        team: Team | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        flag_active: bool = True,
        exposure_frozen: bool = False,
        **fields: Any,
    ) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team,
            key=f"flag-{name}",
            created_by=self.user,
            active=flag_active,
            filters=(
                {"groups": [{"properties": [], "rollout_percentage": 100, EXPOSURE_FROZEN_GROUP_KEY: True}]}
                if exposure_frozen
                else {}
            ),
        )
        return Experiment.objects.create(
            team=team,
            name=name,
            feature_flag=flag,
            created_by=self.user,
            start_date=start_date,
            end_date=end_date,
            **fields,
        )

    def _member_blocked_from(self, experiment: Experiment) -> UserAccessControl:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@example.com", "pw")
        create_access_control(
            team_id=self.team.id,
            resource="experiment",
            resource_id=str(experiment.id),
            access_level="none",
            organization_member_id=OrganizationMembership.objects.get(user=member).id,
        )
        return UserAccessControl(user=member, team=self.team)

    def _list_names(
        self, access: UserAccessControl | None = None, *, status: str = "all", limit: int = 10
    ) -> list[str]:
        page = experiments_list_widget_page(
            self.team, access, status=status, order_by="name", descending=False, created_by_id=None, limit=limit
        )
        return [row.name for row in page.rows]

    def test_list_leaves_out_other_teams_deleted_and_inaccessible_experiments(self) -> None:
        self._experiment("Visible")
        self._experiment("Deleted", deleted=True)
        self._experiment("Other team", team=Team.objects.create(organization=self.organization, name="other"))
        member_access = self._member_blocked_from(self._experiment("Blocked"))

        assert self._list_names() == ["Blocked", "Visible"]
        assert self._list_names(member_access) == ["Visible"]

    @parameterized.expand([("running", "Running"), ("paused", "Paused"), ("exposure_frozen", "Frozen")])
    def test_list_filters_by_status(self, status: str, expected_name: str) -> None:
        now = timezone.now()
        self._experiment("Running", start_date=now)
        self._experiment("Paused", start_date=now, flag_active=False)
        self._experiment("Frozen", start_date=now, exposure_frozen=True)

        assert self._list_names(status=status) == [expected_name]

    def test_list_page_keeps_the_order_and_reports_more_rows(self) -> None:
        for name in ("B", "C", "A"):
            self._experiment(name)

        page = experiments_list_widget_page(
            self.team, None, status="all", order_by="name", descending=True, created_by_id=None, limit=2
        )

        assert [row.name for row in page.rows] == ["C", "B"]
        assert page.has_more is True
        assert self._list_names(limit=3) == ["A", "B", "C"]

    def test_has_accessible_experiments_leaves_out_other_teams_deleted_and_inaccessible_experiments(self) -> None:
        self._experiment("Deleted", deleted=True)
        self._experiment("Other team", team=Team.objects.create(organization=self.organization, name="other"))
        assert has_accessible_experiments(self.team, None) is False

        member_access = self._member_blocked_from(self._experiment("Blocked"))
        assert has_accessible_experiments(self.team, member_access) is False
        assert has_accessible_experiments(self.team, None) is True

    def test_results_leave_out_other_teams_deleted_and_inaccessible_experiments(self) -> None:
        other_team = self._experiment("Other team", team=Team.objects.create(organization=self.organization, name="o"))
        deleted = self._experiment("Deleted", deleted=True)
        blocked = self._experiment("Blocked")
        member_access = self._member_blocked_from(blocked)

        for experiment, access in ((other_team, None), (deleted, None), (blocked, member_access)):
            assert (
                experiment_results_widget(
                    self.team, access, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
                )
                is None
            )
        assert (
            experiment_results_widget(self.team, None, experiment_id=blocked.id, max_metrics_per_section=MAX_METRICS)
            is not None
        )

    @patch(RUNNER)
    def test_results_of_a_draft_run_no_query(self, mock_runner_cls: MagicMock) -> None:
        experiment = self._experiment("Draft", metrics=[_metric("uuid-1", "Mean metric")])

        widget = experiment_results_widget(
            self.team, None, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
        )

        assert widget is not None
        assert widget.status == "draft"
        assert widget.metrics is None
        mock_runner_cls.assert_not_called()

    @patch(RUNNER)
    def test_results_compute_each_section_without_debug_fields(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(
            model_dump=lambda mode="json": {
                "kind": "NewExperimentQueryResponse",
                "baseline": {"key": "control", "number_of_samples": 100, "sum": 40, "sum_squares": 30},
                "variant_results": [{"key": "test", "number_of_samples": 100, "sum": 55, "sum_squares": 40}],
                "clickhouse_sql": "SELECT secret",
            }
        )
        experiment = self._experiment(
            "Running",
            start_date=timezone.now(),
            metrics=[_metric("uuid-1", "Primary metric")],
            metrics_secondary=[_metric("secondary-1", "Secondary metric")],
        )

        widget = experiment_results_widget(
            self.team, None, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
        )

        assert widget is not None and widget.metrics is not None
        assert widget.status == "running"
        assert [metric.name for metric in widget.metrics.primary] == ["Primary metric"]
        assert [metric.name for metric in widget.metrics.secondary] == ["Secondary metric"]
        assert (widget.metrics.primary_total, widget.metrics.secondary_total) == (1, 1)
        for metric in (*widget.metrics.primary, *widget.metrics.secondary):
            assert metric.error is None
            assert metric.metric is not None and metric.metric["metric_type"] == "mean"
            assert metric.result is not None and metric.result["baseline"]["key"] == "control"
            assert "clickhouse_sql" not in metric.result
        assert mock_runner_cls.call_args.kwargs["query"].experiment_id == experiment.id

    @patch(RUNNER)
    def test_results_cap_each_section_independently(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        over_cap = MAX_METRICS + 2
        experiment = self._experiment(
            "Running",
            start_date=timezone.now(),
            metrics=[_metric(f"uuid-{index}", f"Metric {index}") for index in range(over_cap)],
            metrics_secondary=[_metric(f"secondary-{index}", f"Secondary {index}") for index in range(over_cap)],
        )

        widget = experiment_results_widget(
            self.team, None, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
        )

        assert widget is not None and widget.metrics is not None
        assert (widget.metrics.primary_total, widget.metrics.secondary_total) == (over_cap, over_cap)
        assert (len(widget.metrics.primary), len(widget.metrics.secondary)) == (MAX_METRICS, MAX_METRICS)
        assert mock_runner_cls.return_value.run.call_count == 2 * MAX_METRICS

    @patch(RUNNER)
    def test_results_compute_a_shared_metric_with_its_link_overrides(self, mock_runner_cls: MagicMock) -> None:
        mock_runner_cls.return_value.run.return_value = MagicMock(model_dump=lambda mode="json": {})
        experiment = self._experiment("Running", start_date=timezone.now())
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team, name="Shared metric", query=_metric("shared-1", "")
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
        )

        widget = experiment_results_widget(
            self.team, None, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
        )

        assert widget is not None and widget.metrics is not None
        assert [metric.name for metric in widget.metrics.primary] == ["Shared metric"]
        calculated_metric = mock_runner_cls.call_args.kwargs["query"].metric
        assert [breakdown.property for breakdown in calculated_metric.breakdownFilter.breakdowns] == ["$browser"]

    @parameterized.expand([("primary", True), ("secondary", False)])
    @patch(RUNNER)
    def test_results_isolate_and_sanitize_a_metric_failure(
        self, _label: str, is_primary: bool, mock_runner_cls: MagicMock
    ) -> None:
        mock_runner_cls.return_value.run.side_effect = Exception("SELECT * FROM secret_table")
        broken = [_metric("uuid-1", "Broken metric")]
        experiment = self._experiment(
            "Running",
            start_date=timezone.now(),
            metrics=broken if is_primary else [],
            metrics_secondary=[] if is_primary else broken,
        )

        widget = experiment_results_widget(
            self.team, None, experiment_id=experiment.id, max_metrics_per_section=MAX_METRICS
        )

        assert widget is not None and widget.metrics is not None
        (metric,) = widget.metrics.primary or widget.metrics.secondary
        assert metric.error == "Could not compute results for this metric."
        assert "secret_table" not in str(metric)
