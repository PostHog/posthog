import uuid
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from products.warehouse_sources.backend.admin.external_data_job_admin import ExternalDataJobAdmin
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_ADMIN_MODULE = "products.warehouse_sources.backend.admin.external_data_job_admin"
_TERMINAL_STATUSES = [
    ("completed", ExternalDataJob.Status.COMPLETED),
    ("failed", ExternalDataJob.Status.FAILED),
    ("billing_limit_reached", ExternalDataJob.Status.BILLING_LIMIT_REACHED),
    ("billing_limit_too_low", ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW),
]


class TestExternalDataJobAdminMarkFailed(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = ExternalDataJobAdmin(ExternalDataJob, AdminSite())
        self.factory = RequestFactory()

    def _request(self, method: str, data: dict | None = None):
        request = getattr(self.factory, method)("/", data=data or {})
        request.session = {}
        request._messages = FallbackStorage(request)
        request.user = self.user
        return request

    def _job(self, *, job_status: str, schema_status: str = ExternalDataSchema.Status.RUNNING) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Running",
            source_type="Stripe",
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source=source, name="invoices", status=schema_status
        )
        return ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=source,
            schema=schema,
            status=job_status,
            workflow_id="wf-123",
            workflow_run_id="wfr-123",
        )

    def test_marks_job_and_schema_failed_and_terminates_workflow(self) -> None:
        # The whole point of the recovery action: an orphaned Running job leaves the schema stuck on
        # Running (the schema status is what the UI and the schedule guard read). Flipping only the job
        # would leave the schema wrong — so assert both, plus that the dead workflow is terminated.
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow") as mock_terminate:
            response = self.admin.mark_failed_view(self._request("post", {"reason": "worker OOMed"}), str(job.pk))

        assert response.status_code == 302
        job.refresh_from_db()
        job.schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.schema.status == ExternalDataSchema.Status.FAILED
        assert job.latest_error == "worker OOMed"
        assert job.finished_at is not None
        mock_terminate.assert_called_once_with("wf-123", reason="worker OOMed")

    def test_default_error_when_no_reason_given(self) -> None:
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow"):
            self.admin.mark_failed_view(self._request("post", {}), str(job.pk))

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.latest_error is not None and "Marked Failed via admin" in job.latest_error

    def test_terminate_failure_still_marks_failed(self) -> None:
        # A workflow that's already closed (or never existed) makes terminate raise — that must not
        # abort the recovery, otherwise a job whose workflow is already gone can never be cleared.
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow", side_effect=Exception("not running")):
            response = self.admin.mark_failed_view(self._request("post", {}), str(job.pk))

        assert response.status_code == 302
        job.refresh_from_db()
        job.schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.schema.status == ExternalDataSchema.Status.FAILED

    @parameterized.expand(_TERMINAL_STATUSES)
    def test_noop_when_not_running(self, _name: str, status: str) -> None:
        # A terminal job must be left untouched: no re-fail, no workflow terminate, and crucially the
        # schema (left Running here) isn't dragged to Failed off the back of an already-finished job.
        job = self._job(job_status=status)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow") as mock_terminate:
            response = self.admin.mark_failed_view(self._request("post", {"reason": "nope"}), str(job.pk))

        assert response.status_code == 302
        mock_terminate.assert_not_called()
        job.refresh_from_db()
        job.schema.refresh_from_db()
        assert job.status == status
        assert job.schema.status == ExternalDataSchema.Status.RUNNING

    def test_get_does_not_mutate(self) -> None:
        # Mutation only on POST; a GET must be a pure redirect (also guards the app-label reverse in
        # _change_url from silently breaking after the model moved to the warehouse_sources app).
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow") as mock_terminate:
            response = self.admin.mark_failed_view(self._request("get"), str(job.pk))

        assert response.status_code == 302
        assert str(job.pk) in response.url
        mock_terminate.assert_not_called()
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING

    def test_denies_without_change_permission(self) -> None:
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)

        with (
            patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow") as mock_terminate,
            patch.object(self.admin, "has_change_permission", return_value=False),
        ):
            with self.assertRaises(PermissionDenied):
                self.admin.mark_failed_view(self._request("post", {"reason": "x"}), str(job.pk))

        mock_terminate.assert_not_called()
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING

    @freeze_time("2026-01-15 12:00:00")
    def test_preserves_existing_finished_at(self) -> None:
        existing = timezone.now() - timedelta(hours=1)
        job = self._job(job_status=ExternalDataJob.Status.RUNNING)
        ExternalDataJob.objects.filter(pk=job.pk).update(finished_at=existing)

        with patch(f"{_ADMIN_MODULE}.terminate_external_data_workflow"):
            self.admin.mark_failed_view(self._request("post", {"reason": "x"}), str(job.pk))

        job.refresh_from_db()
        assert job.finished_at == existing


class TestExternalDataJobAdminChangeView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = ExternalDataJobAdmin(ExternalDataJob, AdminSite())
        self.factory = RequestFactory()

    def _context(self, job: ExternalDataJob) -> dict:
        request = self.factory.get("/")
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        captured: dict = {}

        def _capture(_admin, _request, _object_id, _form_url, extra_context):
            captured.update(extra_context)
            return HttpResponse(status=200)

        with patch("django.contrib.admin.ModelAdmin.change_view", _capture):
            self.admin.change_view(request, str(job.pk))
        return captured

    def _job(self, *, status: str, with_schema: bool = True) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Running",
            source_type="Postgres",
        )
        schema = (
            ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="customers")
            if with_schema
            else None
        )
        return ExternalDataJob.objects.create(
            team_id=self.team.pk, pipeline=source, schema=schema, status=status, workflow_id="wf-1"
        )

    def test_running_job_context_exposes_recovery_urls(self) -> None:
        # Guards the recovery-UI wiring and, importantly, that the reverse() names resolve after the
        # model moved to the warehouse_sources app (a wrong app_label raises NoReverseMatch here).
        context = self._context(self._job(status=ExternalDataJob.Status.RUNNING))
        assert context["is_running"] is True
        assert "mark_failed_url" in context
        assert "schema_admin_url" in context

    @parameterized.expand(_TERMINAL_STATUSES)
    def test_terminal_job_is_not_running(self, _name: str, status: str) -> None:
        assert self._context(self._job(status=status))["is_running"] is False

    def test_schema_url_omitted_when_no_schema(self) -> None:
        context = self._context(self._job(status=ExternalDataJob.Status.RUNNING, with_schema=False))
        assert "schema_admin_url" not in context
