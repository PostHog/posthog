from datetime import UTC, datetime

from unittest.mock import patch

from django.db.models.signals import post_save
from django.test import TestCase

from parameterized import parameterized

from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import handle_hog_flow_batch_job_created


class TestHogFlowBatchJob(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

        # Create a HogFlow for testing
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow",
            actions=[
                {
                    "id": "trigger_node",
                    "name": "trigger_1",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {
                            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                        },
                    },
                }
            ],
        )

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_creation(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(
            team=self.team,
            hog_flow=self.hog_flow,
            created_by=self.user,
            variables=[{"key": "event_name", "value": "$pageview"}],
        )

        assert batch_job.team == self.team
        assert batch_job.hog_flow == self.hog_flow
        assert batch_job.created_by == self.user
        assert batch_job.status == HogFlowBatchJob.State.QUEUED
        assert batch_job.variables == [{"key": "event_name", "value": "$pageview"}]
        assert str(batch_job) == f"HogFlow batch run {batch_job.id}"
        mock_create_invocation.assert_called_once()

    @parameterized.expand(
        [
            ("single_realtime_cohort", "realtime", None, True),
            ("realtime_cohort_with_another_condition", "realtime", "with_property", False),
            # Postgres membership can't exclude test accounts, so that audience keeps the Django query.
            ("realtime_cohort_with_test_account_filter", "realtime", "test_accounts", False),
            ("non_realtime_cohort", "not_realtime", None, False),
        ]
    )
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_dispatch_names_a_realtime_cohort_audience(
        self, _name, cohort_kind, shape, expect_realtime, mock_create_invocation
    ):
        behavioral = {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "key": "$pageview",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                        "value": "performed_event",
                        "type": "behavioral",
                    }
                ],
            }
        }
        cohort = Cohort.objects.create(
            team=self.team,
            name="c",
            filters=behavioral,
            cohort_type=CohortType.REALTIME if cohort_kind == "realtime" else None,
            last_backfill_events_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_backfill_person_properties_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        properties: list[dict] = [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]
        if shape == "with_property":
            properties.append({"key": "plan", "type": "person", "value": "pro", "operator": "exact"})

        filters: dict = {"properties": properties}
        if shape == "test_accounts":
            filters["filter_test_accounts"] = True

        HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, filters=filters)

        expected = {"id": cohort.pk, "team_id": self.team.pk} if expect_realtime else None
        assert mock_create_invocation.call_args.kwargs["realtime_cohort"] == expected

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_fails_when_its_realtime_cohort_is_no_longer_ready(self, mock_create_invocation):
        # An edit after the save clears the cohort's readiness; its membership is partial until it recalculates.
        cohort = Cohort.objects.create(
            team=self.team,
            name="c",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                            "value": "performed_event",
                            "type": "behavioral",
                        }
                    ],
                }
            },
        )

        job = HogFlowBatchJob.objects.create(
            team=self.team,
            hog_flow=self.hog_flow,
            filters={"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]},
        )

        mock_create_invocation.assert_not_called()
        job.refresh_from_db()
        assert job.status == HogFlowBatchJob.State.FAILED

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_can_fail(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

        batch_job.status = HogFlowBatchJob.State.FAILED
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.FAILED

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    @patch("products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.handle_hog_flow_batch_job_created")
    def test_hog_flow_batch_job_created_signal(self, mock_handler, mock_create_invocation):
        # Disconnect the signal temporarily to test it

        post_save.disconnect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

        try:
            # Reconnect with our mock
            post_save.connect(mock_handler, sender=HogFlowBatchJob)

            batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

            mock_handler.assert_called_once()
            call_kwargs = mock_handler.call_args[1]
            assert call_kwargs["sender"] == HogFlowBatchJob
            assert call_kwargs["instance"] == batch_job
            assert call_kwargs["created"] is True
        finally:
            # Reconnect the original signal
            post_save.disconnect(mock_handler, sender=HogFlowBatchJob)
            post_save.connect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_without_created_by(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

        assert batch_job.created_by is None
        assert batch_job.team == self.team

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_complex_variables(self, mock_create_invocation):
        variables = [
            {"key": "first_name", "value": "John"},
            {"key": "last_name", "value": "Doe"},
            {"key": "email", "value": "john@posthog.com"},
        ]
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=variables)

        assert batch_job.variables == variables
