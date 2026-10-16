from datetime import UTC, datetime

from unittest.mock import patch

from django.db.models.signals import post_save
from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.models.user import User

from products.cohorts.backend.facade.ready_signals import realtime_cohort_ready
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import (
    REALTIME_COHORT_WAIT_LIMIT,
    handle_hog_flow_batch_job_created,
)


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="all")
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

    def _realtime_cohort(self, *, ready: bool) -> Cohort:
        stamp = datetime(2026, 1, 1, tzinfo=UTC) if ready else None
        return Cohort.objects.create(
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
            last_backfill_events_at=stamp,
            last_backfill_person_properties_at=stamp,
        )

    def _realtime_audience(self, cohort: Cohort) -> dict:
        return {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "in"}]}

    @patch("products.workflows.backend.tasks.batch_jobs.resume_batch_jobs_waiting_for_realtime_cohort.delay")
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_hog_flow_batch_job_parks_its_resolver_while_the_cohort_calculates(
        self, mock_create_invocation, mock_resume_task
    ):
        cohort = self._realtime_cohort(ready=False)

        with self.captureOnCommitCallbacks(execute=True):
            job = HogFlowBatchJob.objects.create(
                team=self.team, hog_flow=self.hog_flow, filters=self._realtime_audience(cohort)
            )

        job.refresh_from_db()
        assert job.status == HogFlowBatchJob.State.WAITING
        assert mock_create_invocation.call_args.kwargs["realtime_cohort"] == {
            "id": cohort.pk,
            "team_id": self.team.pk,
            "wait_until": (job.created_at + REALTIME_COHORT_WAIT_LIMIT).isoformat(),
        }
        # A cohort that finished between the readiness check and the park still wakes the run.
        mock_resume_task.assert_called_once_with(self.team.pk, cohort.pk)

    @parameterized.expand(
        [
            ("resumed", "calculated", "resumed", "queued", True),
            # A second wake of the same run is a no-op on the CDP side.
            ("already_resumed", "calculated", "already_resumed", "queued", True),
            ("still_calculating", "calculating", "resumed", "waiting", False),
            # The stamps are set, but the pipeline doesn't keep the membership current for this team.
            ("team_off_realtime_allowlist", "off_allowlist", "resumed", "waiting", False),
            # The resolver isn't parked, so the CDP API didn't wake it.
            ("resolver_running", "calculated", "job_running", "waiting", True),
            ("another_cohort", "another_cohort", "resumed", "waiting", False),
        ]
    )
    @patch("products.workflows.backend.services.batch_jobs.resume_hog_flow_batch_job")
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_ready_cohort_resumes_the_runs_parked_on_it(
        self,
        _name,
        cohort_state,
        resume_outcome,
        expected_status,
        expect_resume,
        _mock_create_invocation,
        mock_resume,
    ):
        cohort = self._realtime_cohort(ready=False)
        job = HogFlowBatchJob.objects.create(
            team=self.team, hog_flow=self.hog_flow, filters=self._realtime_audience(cohort)
        )
        if cohort_state != "calculating":
            Cohort.objects.filter(pk=cohort.pk).update(
                last_backfill_events_at=datetime(2026, 1, 1, tzinfo=UTC),
                last_backfill_person_properties_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ready_cohort = self._realtime_cohort(ready=True) if cohort_state == "another_cohort" else cohort
        mock_resume.return_value.status_code = 200
        mock_resume.return_value.json.return_value = {"outcome": resume_outcome}

        allowlist = "none" if cohort_state == "off_allowlist" else "all"
        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=allowlist):
            realtime_cohort_ready.send(sender=Cohort, team_id=self.team.pk, cohort_id=ready_cohort.pk)

        job.refresh_from_db()
        assert job.status == expected_status
        assert mock_resume.called == expect_resume
        if expect_resume:
            assert mock_resume.call_args.kwargs == {
                "team_id": self.team.pk,
                "hog_flow_id": str(self.hog_flow.id),
                "batch_job_id": str(job.id),
            }

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
