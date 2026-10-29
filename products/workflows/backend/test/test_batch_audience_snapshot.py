from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework import exceptions

from posthog.errors import ClickHouseQueryTimeOut
from posthog.models.user import User

from products.workflows.backend.facade.enums import HogFlowBatchJobAudienceStatus, HogFlowBatchJobState
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob, HogFlowBatchJobAudienceMember
from products.workflows.backend.services.batch_audience_snapshot import (
    get_audience_snapshot_page,
    request_audience_snapshot,
    resolve_audience_snapshot,
)
from products.workflows.backend.services.batch_jobs import set_batch_job_status

PERSON_IDS = [f"0197000{i}-0000-0000-0000-000000000000" for i in range(1, 8)]

QUERY = "products.workflows.backend.services.batch_audience_snapshot.get_batch_audience_person_ids_snapshot"
RESOLVE_TASK = "products.workflows.backend.tasks.batch_jobs.resolve_batch_job_audience_snapshot.delay"
DELETE_TASK = "products.workflows.backend.tasks.batch_jobs.delete_batch_job_audience_snapshot.delay"
DISPATCH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)


@patch(DISPATCH)
class TestBatchAudienceSnapshot(TestCase):
    def setUp(self):
        super().setUp()
        _org, self.team, self.user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow",
            trigger={"type": "batch", "filters": {"properties": []}},
            actions=[{"id": "trigger_node", "name": "trigger", "type": "trigger", "config": {"type": "batch"}}],
        )

    def _job(self, **kwargs) -> HogFlowBatchJob:
        return HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, **kwargs)

    def _members(self, job: HogFlowBatchJob) -> list[str]:
        return [
            str(person_id)
            for person_id in HogFlowBatchJobAudienceMember.objects.for_team(self.team.pk)
            .filter(batch_job=job)
            .order_by("person_id")
            .values_list("person_id", flat=True)
        ]

    def test_request_starts_the_resolution_once_and_then_reports_its_status(self, _dispatch):
        job = self._job()

        with patch(RESOLVE_TASK) as mock_task, self.captureOnCommitCallbacks(execute=True):
            first = request_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key="email", max_audience_size=5
            )
            again = request_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key="email", max_audience_size=5
            )

        assert first.status == HogFlowBatchJobAudienceStatus.RESOLVING
        assert again.status == HogFlowBatchJobAudienceStatus.RESOLVING
        mock_task.assert_called_once_with(self.team.pk, str(job.id), "email", 5)

    def test_resolve_stores_the_audience_and_marks_it_ready(self, _dispatch):
        job = self._job(audience_status=HogFlowBatchJobAudienceStatus.RESOLVING)

        with patch(QUERY, return_value=PERSON_IDS) as mock_query:
            resolve_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key="email", max_audience_size=100
            )

        job.refresh_from_db()
        assert job.audience_status == HogFlowBatchJobAudienceStatus.READY
        assert job.audience_size == len(PERSON_IDS)
        assert self._members(job) == PERSON_IDS
        assert mock_query.call_args.kwargs["dedupe_key"] == "email"
        assert mock_query.call_args.kwargs["limit"] == 100
        # The whole audience runs under the long cap, not the interactive one.
        assert mock_query.call_args.kwargs["settings"].max_execution_time == 1200

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut(), "timed out after 20 minutes"),
            ("bad_filter", exceptions.ValidationError("Unknown property"), "Unknown property"),
            ("other", RuntimeError("connection reset"), "Audience query failed"),
        ]
    )
    def test_resolve_records_a_reason_the_customer_can_read_when_the_query_fails(
        self, _dispatch, _name, error, expected_reason
    ):
        job = self._job(audience_status=HogFlowBatchJobAudienceStatus.RESOLVING)

        with patch(QUERY, side_effect=error):
            resolve_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key=None, max_audience_size=100
            )

        job.refresh_from_db()
        assert job.audience_status == HogFlowBatchJobAudienceStatus.FAILED
        assert expected_reason in (job.audience_error or "")
        assert "connection reset" not in (job.audience_error or "")

    def test_resolve_skips_a_run_that_already_ended(self, _dispatch):
        job = self._job(status=HogFlowBatchJobState.CANCELLED, audience_status=HogFlowBatchJobAudienceStatus.RESOLVING)

        with patch(QUERY) as mock_query:
            resolve_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key=None, max_audience_size=100
            )

        mock_query.assert_not_called()

    def test_pages_the_stored_audience_in_id_order(self, _dispatch):
        job = self._job(audience_status=HogFlowBatchJobAudienceStatus.RESOLVING)
        with patch(QUERY, return_value=PERSON_IDS):
            resolve_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key=None, max_audience_size=100
            )

        collected: list[str] = []
        cursor = None
        with patch(
            "products.workflows.backend.services.batch_audience_snapshot.person_audience_page_size", return_value=3
        ):
            while True:
                page = get_audience_snapshot_page(team_id=self.team.pk, batch_job_id=str(job.id), cursor=cursor)
                collected.extend(page.ids)
                if not page.has_more:
                    break
                cursor = page.ids[-1]

        assert collected == PERSON_IDS

    def test_ending_the_run_drops_its_stored_audience(self, _dispatch):
        job = self._job(audience_status=HogFlowBatchJobAudienceStatus.RESOLVING)
        with patch(QUERY, return_value=PERSON_IDS):
            resolve_audience_snapshot(
                team_id=self.team.pk, batch_job_id=str(job.id), dedupe_key=None, max_audience_size=100
            )
        assert self._members(job)

        with patch(DELETE_TASK) as mock_delete, self.captureOnCommitCallbacks(execute=True):
            set_batch_job_status(team_id=self.team.pk, batch_job_id=job.id, status=HogFlowBatchJobState.COMPLETED)

        mock_delete.assert_called_once_with(self.team.pk, str(job.id))
