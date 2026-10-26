from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog, Detail, log_activity
from posthog.models.team.team import Team

from products.event_definitions.backend.models import EventDefinition
from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag

NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
Code = ExperimentHealthFindingCode
WARNING = ExperimentHealthFindingSeverity.WARNING


def _mean(event: str, **fields: Any) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": event},
        **fields,
    }


class TestEventsReceived(BaseTest):
    @parameterized.expand(
        [
            (
                "custom_exposure_event",
                {"event": "checkout_viewed", "properties": []},
                ("exposure_event_not_ingested", {"event": "checkout_viewed"}),
            ),
            (
                "flag_call_filter_on_another_flag",
                {
                    "event": "$feature_flag_called",
                    "properties": [
                        {"key": "$feature_flag", "type": "event", "value": ["pricing-test"], "operator": "exact"}
                    ],
                },
                ("filter_on_another_flag", {"flag_key": "checkout-test", "filter_flag_keys": "pricing-test"}),
            ),
        ]
    )
    def test_reads_the_events_the_project_received(
        self, _name: str, exposure_config: dict[str, Any], expected_exposure: tuple[str, dict[str, str]]
    ) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.project, name="Sibling")
        EventDefinition.objects.create(team=sibling, project=self.project, name="purchase", last_seen_at=timezone.now())
        # Wizard writes a definition without `last_seen_at` for an event it planned.
        EventDefinition.objects.create(team=self.team, project=self.project, name="signup", last_seen_at=None)
        for name in ("refund", "upgrade"):
            with self.captureOnCommitCallbacks(execute=True):
                log_activity(
                    organization_id=self.organization.id,
                    team_id=sibling.id,
                    user=self.user,
                    was_impersonated=False,
                    item_id=name,
                    scope="EventDefinition",
                    activity="deleted",
                    detail=Detail(name=name, changes=None),
                )
        ActivityLog.objects.filter(item_id="upgrade").update(created_at=timezone.now() - timedelta(days=4))
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=2),
            metrics=[_mean("purchase", uuid="revenue", name="Revenue")],
            metrics_secondary=[
                _mean("signup", uuid="signups"),
                _mean("refund", uuid="refunds"),
                _mean("upgrade", uuid="upgrades"),
            ],
            exposure_criteria={"exposure_config": {"kind": "ExperimentEventExposureConfig", **exposure_config}},
        )
        shared = ExperimentSavedMetric.objects.create(
            team=self.team, name="Checkout started", created_by=self.user, query=_mean("checkout_started", uuid="c")
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=shared, metadata={"type": "primary"})

        health = get_experiment_health(team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES)

        findings = {finding.code: finding for finding in health.findings}
        metric = findings[Code.METRIC_EVENT_NOT_INGESTED]
        self.assertEqual(metric.severity, WARNING)
        self.assertEqual(
            dict(metric.evidence),
            {
                "metric_1": "Mean signup",
                "metric_1_role": "secondary",
                "metric_1_events": "signup",
                "metric_2": "Mean upgrade",
                "metric_2_role": "secondary",
                "metric_2_events": "upgrade",
                "metric_3": "Checkout started",
                "metric_3_role": "primary",
                "metric_3_events": "checkout_started",
            },
        )
        exposure = findings[Code.EXPOSURE_CRITERIA_CANNOT_MATCH]
        self.assertEqual((exposure.subcode, dict(exposure.evidence)), expected_exposure)
        self.assertEqual(exposure.severity, WARNING)

    def test_a_filter_on_a_deleted_flags_own_key_can_match(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        flag.key, flag.deleted = flag.tombstoned_key(), True
        flag.save()
        experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=2),
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [
                        {"key": "$feature_flag", "type": "event", "value": ["checkout-test"], "operator": "exact"}
                    ],
                }
            },
        )

        health = get_experiment_health(team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES)

        self.assertNotIn(Code.EXPOSURE_CRITERIA_CANNOT_MATCH, {finding.code for finding in health.findings})

    def test_shared_metrics_add_no_queries(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        experiment = Experiment.objects.create(team=self.team, name="Checkout", feature_flag=flag)

        query_counts = []
        for number in range(3):
            shared = ExperimentSavedMetric.objects.create(
                team=self.team,
                name=f"Shared {number}",
                created_by=self.user,
                query=_mean(f"event_{number}", uuid=str(number)),
            )
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=shared, metadata={"type": "primary"}
            )
            with CaptureQueriesContext(connection) as queries:
                get_experiment_health(team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES)
            query_counts.append(len(queries))

        self.assertEqual(len(set(query_counts)), 1, query_counts)
