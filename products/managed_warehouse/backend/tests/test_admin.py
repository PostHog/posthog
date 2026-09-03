from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404, HttpRequest
from django.test import RequestFactory
from django.urls import reverse

from rest_framework.response import Response

from posthog.models import Organization, Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.admin.duckgres_server_admin import DuckgresServerAdmin
from products.managed_warehouse.backend.admin.view_translation_admin import (
    ManagedWarehouseViewTranslationJobAdmin,
    ManagedWarehouseViewTranslationJobForm,
    ManagedWarehouseViewTranslationResultAdmin,
)
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)

MW = "products.managed_warehouse.backend.presentation.views"


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _messages(request) -> list[str]:
    return [str(m) for m in get_messages(request)]


class TestManagedWarehouseViewTranslationJobAdmin(BaseTest):
    def test_selected_view_form_normalizes_saved_query_ids(self) -> None:
        DuckgresServer.objects.create(
            organization=self.organization,
            host="managed.example.com",
            database="ducklake",
            username="root",
            password="secret",
        )
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="selected_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
        )
        form = ManagedWarehouseViewTranslationJobForm(
            data={
                "organization": str(self.organization.id),
                "scope": ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS,
                "selected_saved_query_ids": f"{saved_query.id},\n{saved_query.id}",
            }
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["selected_saved_query_ids"] == [str(saved_query.id)]

    def test_adding_a_job_dispatches_it_after_commit(self) -> None:
        request = RequestFactory().post("/admin/managed_warehouse/managedwarehouseviewtranslationjob/add/")
        request.user = self.user
        model_admin = ManagedWarehouseViewTranslationJobAdmin(ManagedWarehouseViewTranslationJob, AdminSite())
        job = ManagedWarehouseViewTranslationJob(organization=self.organization)

        with (
            patch(
                "products.managed_warehouse.backend.admin.view_translation_admin._start_translation_job"
            ) as start_job,
            self.captureOnCommitCallbacks(execute=True),
        ):
            model_admin.save_model(request, job, MagicMock(), change=False)

        job.refresh_from_db()
        assert job.created_by == self.user
        assert job.status == ManagedWarehouseViewTranslationJob.Status.PENDING
        start_job.assert_called_once_with(job.id, self.organization.id)

    def test_retry_selected_results_creates_a_selected_view_job(self) -> None:
        saved_queries = [
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"kind": "HogQLQuery", "query": "SELECT 1"},
            )
            for name in ["failed_view", "stale_view"]
        ]
        source_job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization,
            status=ManagedWarehouseViewTranslationJob.Status.COMPLETED_WITH_ERRORS,
        )
        results = [
            ManagedWarehouseViewTranslationResult.all_teams.create(
                job=source_job,
                team=self.team,
                saved_query_id=saved_query.id,
                saved_query_name=saved_query.name,
                source_query_hash="0" * 64,
                status=status,
            )
            for saved_query, status in zip(
                saved_queries,
                [
                    ManagedWarehouseViewTranslationResult.Status.FAILED,
                    ManagedWarehouseViewTranslationResult.Status.STALE,
                ],
                strict=True,
            )
        ]
        request = RequestFactory().post("/admin/managed_warehouse/managedwarehouseviewtranslationresult/")
        request.user = self.user
        _attach_messages(request)
        model_admin = ManagedWarehouseViewTranslationResultAdmin(
            ManagedWarehouseViewTranslationResult,
            AdminSite(),
        )

        with (
            patch(
                "products.managed_warehouse.backend.admin.view_translation_admin._start_translation_job"
            ) as start_job,
            self.captureOnCommitCallbacks(execute=True),
        ):
            model_admin.retry_selected_translations(
                request,
                ManagedWarehouseViewTranslationResult.all_teams.filter(id__in=[result.id for result in results]),
            )

        retry_job = ManagedWarehouseViewTranslationJob.objects.exclude(id=source_job.id).get()
        assert retry_job.trigger_source == ManagedWarehouseViewTranslationJob.TriggerSource.RETRY
        assert retry_job.scope == ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS
        assert retry_job.retry_of == source_job
        assert set(retry_job.selected_saved_query_ids) == {str(saved_query.id) for saved_query in saved_queries}
        start_job.assert_called_once_with(retry_job.id, self.organization.id)


class TestDuckgresServerAdminProvision(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self._grant_admin_permissions()
        self.factory = RequestFactory()
        self.admin = DuckgresServerAdmin(DuckgresServer, AdminSite())

    def _post(self, url: str, data: dict) -> HttpRequest:
        request = self.factory.post(url, data)
        request.user = self.user
        _attach_messages(request)
        return request

    def _get(self, url: str) -> HttpRequest:
        request = self.factory.get(url)
        request.user = self.user
        _attach_messages(request)
        return request

    def _head(self, url: str) -> HttpRequest:
        request = self.factory.head(url)
        request.user = self.user
        _attach_messages(request)
        return request

    def _server(self) -> DuckgresServer:
        return DuckgresServer.objects.create(
            organization=self.organization, host="h", port=5432, database="ducklake", username="root", password="x"
        )

    def _grant_admin_permissions(self) -> None:
        permissions = Permission.objects.filter(
            content_type__app_label="managed_warehouse",
            codename__in=[
                "add_duckgresserver",
                "change_duckgresserver",
                "delete_duckgresserver",
            ],
        )
        self.user.user_permissions.add(*permissions)

    def test_change_fieldsets_do_not_expose_password_for_existing_server(self) -> None:
        request = self._get("/admin/posthog/duckgresserver/")
        server = self._server()

        field_names = {
            field_name
            for _, fieldset_options in self.admin.get_fieldsets(request, server)
            for field_name in fieldset_options["fields"]
        }

        assert "username" in field_names
        assert "password" not in field_names

    def test_provision_post_calls_managed_warehouse_bypassing_flag(self) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "schema_name": "prod_events",
            },
        )
        body = {"username": "root", "password": "sup3r-secret-pw"}
        with patch(f"{MW}.provision", return_value=Response(body, status=202)) as mock_provision:
            response = self.admin.provision_view(request)

        mock_provision.assert_called_once_with(
            self.organization.id, "my-warehouse", self.team.id, "prod_events", require_enabled=False
        )
        # Success renders the credentials once, in the page body...
        assert response.status_code == 200
        assert b"sup3r-secret-pw" in response.content
        # ...and the password must NOT leak into the message framework (it persists
        # to the session/cookie store).
        assert all("sup3r-secret-pw" not in m for m in _messages(request))

    def test_provision_failure_surfaces_error_without_rendering_password(self) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "schema_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision", return_value=Response({"error": "nope"}, status=400)):
            response = self.admin.provision_view(request)

        # Failures still flash the error and redirect back to the form.
        assert response.status_code == 302
        assert any("Failed (status 400): nope" in m for m in _messages(request))

    def test_provision_rejects_team_org_mismatch(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org)
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(other_team.id),
                "database_name": "my-warehouse",
                "schema_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision") as mock_provision:
            self.admin.provision_view(request)

        mock_provision.assert_not_called()
        assert any("does not belong to organization" in m for m in _messages(request))

    def test_provision_surfaces_helper_error(self) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "schema_name": "prod_events",
            },
        )
        with patch(f"{MW}.provision", return_value=Response({"error": "boom"}, status=400)):
            self.admin.provision_view(request)

        assert any("Failed (status 400): boom" in m for m in _messages(request))

    def test_enable_backfill_post_calls_helper_bypassing_flag(self) -> None:
        server = self._server()
        request = self._post(
            f"/admin/posthog/duckgresserver/{server.pk}/enable-backfill/",
            {"team_id": str(self.team.id), "schema_name": "env_b"},
        )
        with patch(
            f"{MW}.onboard_team", return_value=Response({"onboarded": True, "schema_name": "env_b"}, status=200)
        ) as mock_onboard:
            self.admin.enable_backfill_view(request, str(server.pk))

        mock_onboard.assert_called_once_with(self.organization.id, self.team.id, "env_b", require_enabled=False)

    def test_enable_backfill_invalid_server_returns_404(self) -> None:
        request = self._get("/admin/posthog/duckgresserver/999999/enable-backfill/")

        with self.assertRaises(Http404):
            self.admin.enable_backfill_view(request, "999999")

    def test_deprovision_post_calls_helper_bypassing_flag(self) -> None:
        server = self._server()
        request = self._post(f"/admin/posthog/duckgresserver/{server.pk}/deprovision/", {})
        with patch(f"{MW}.deprovision", return_value=Response({"status": "ok"}, status=200)) as mock_deprovision:
            self.admin.deprovision_view(request, str(server.pk))

        mock_deprovision.assert_called_once_with(self.organization.id, require_enabled=False)

    def test_deprovision_invalid_server_returns_404(self) -> None:
        request = self._get("/admin/posthog/duckgresserver/999999/deprovision/")

        with self.assertRaises(Http404):
            self.admin.deprovision_view(request, "999999")

    def test_deprovision_head_does_not_call_helper(self) -> None:
        server = self._server()
        request = self._head(f"/admin/posthog/duckgresserver/{server.pk}/deprovision/")

        with patch(f"{MW}.deprovision") as mock_deprovision:
            response = self.admin.deprovision_view(request, str(server.pk))

        assert response.status_code == 405
        mock_deprovision.assert_not_called()

    def test_deprovision_failure_returns_to_change_page_and_logs(self) -> None:
        server = self._server()
        request = self._post(f"/admin/posthog/duckgresserver/{server.pk}/deprovision/", {})

        with (
            patch(f"{MW}.deprovision", return_value=Response({"error": "still running"}, status=409)),
            patch("products.managed_warehouse.backend.admin.duckgres_server_admin.logger.warning") as mock_warning,
        ):
            response = self.admin.deprovision_view(request, str(server.pk))

        assert response["Location"] == reverse("admin:managed_warehouse_duckgresserver_change", args=[server.pk])
        assert any("Failed (status 409): still running" in message for message in _messages(request))
        mock_warning.assert_called_once_with(
            "admin_managed_warehouse_action_failed",
            action=f"Deprovisioned managed warehouse for org {self.organization.id}",
            triggered_by=self.user.email,
            status_code=409,
            error="still running",
        )
