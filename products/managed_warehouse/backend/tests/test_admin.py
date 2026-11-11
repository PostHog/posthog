from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.forms.models import model_to_dict
from django.http import HttpRequest
from django.test import RequestFactory
from django.urls import reverse

from parameterized import parameterized
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
    ManagedWarehouseSourceLifecycle,
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
        assert "trino_password" not in field_names
        assert "new_trino_password" in field_names

    def test_change_form_sets_encrypted_trino_password_without_revealing_or_erasing_it(self) -> None:
        server = self._server()
        request = self._get("/admin/posthog/duckgresserver/")
        form_class = self.admin.get_form(request, server)
        assert "trino_password" not in form_class.base_fields
        assert "password" not in form_class.base_fields

        data = model_to_dict(server)
        data["new_trino_password"] = "trino-test-secret"
        form = form_class(data=data, instance=server)
        assert form.is_valid(), form.errors
        form.save()

        server.refresh_from_db()
        assert server.trino_password == "trino-test-secret"
        with connection.cursor() as cursor:
            cursor.execute("SELECT trino_password FROM posthog_duckgresserver WHERE id = %s", [str(server.id)])
            stored = cursor.fetchone()[0]
        assert stored != "trino-test-secret"
        assert stored.startswith("gAAAAA")
        assert "trino-test-secret" not in form_class(instance=server).as_p()

        form = form_class(data=model_to_dict(server), instance=server)
        assert form.is_valid(), form.errors
        form.save()
        server.refresh_from_db()
        assert server.trino_password == "trino-test-secret"

    @parameterized.expand([False, True])
    def test_provision_post_calls_managed_warehouse_bypassing_flag(self, internal_only: bool) -> None:
        request = self._post(
            "/admin/posthog/duckgresserver/provision/",
            {
                "organization_id": str(self.organization.id),
                "team_id": str(self.team.id),
                "database_name": "my-warehouse",
                "schema_name": "prod_events",
                **({"internal_only": "on"} if internal_only else {}),
            },
        )
        body = {"username": "root", "password": "sup3r-secret-pw"}
        with patch(f"{MW}.provision", return_value=Response(body, status=202)) as mock_provision:
            response = self.admin.provision_view(request)

        mock_provision.assert_called_once_with(
            self.organization.id,
            "my-warehouse",
            self.team.id,
            "prod_events",
            require_enabled=False,
            triggered_by=f"django-admin:{self.user.email}",
            internal_only=internal_only,
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

    def test_change_form_links_to_the_console_panel(self) -> None:
        server = self._server()
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:managed_warehouse_duckgresserver_change", args=[server.pk]))

        assert response.status_code == 200
        assert (
            f"/admin/console/organizations/{self.organization.id}/#panel-managed-warehouse" in response.content.decode()
        )


class TestManagedWarehouseConsolePanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.organization_url = f"/admin/console/organizations/{self.organization.id}/"

    def _server(self) -> DuckgresServer:
        return DuckgresServer.objects.create(
            organization=self.organization,
            host="duckgres.example.com",
            port=5432,
            database="ducklake",
            username="root",
            password="example-password",
        )

    def test_panel_status_and_operations_follow_the_warehouse_lifecycle(self) -> None:
        response = self.client.get(self.organization_url)
        assert "Not provisioned" in response.content.decode()
        assert "Deprovision warehouse" not in response.content.decode()

        self._server()
        response = self.client.get(self.organization_url)
        content = response.content.decode()

        assert "Managed warehouse" in content
        assert "duckgres.example.com" in content
        assert "Enable backfill for a team" in content and "Deprovision warehouse" in content
        assert "example-password" not in content

        ManagedWarehouseSourceLifecycle.objects.create(organization=self.organization, desired_active=False)
        content = self.client.get(self.organization_url).content.decode()

        assert "Deprovisioned" in content
        assert "Enable backfill for a team" not in content and "Deprovision warehouse" in content

    def test_enable_backfill_calls_helper_bypassing_flag(self) -> None:
        self._server()
        with patch(
            f"{MW}.onboard_team", return_value=Response({"onboarded": True, "schema_name": "env_b"}, status=200)
        ) as mock_onboard:
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/enable-backfill/",
                {"team_id": str(self.team.id), "schema_name": "env_b", "reason": "Customer asked"},
            )

        assert response.status_code == 302
        mock_onboard.assert_called_once_with(
            self.organization.id,
            self.team.id,
            "env_b",
            require_enabled=False,
            triggered_by=f"django-admin:{self.user.email}",
        )
        assert any("Onboarded team" in m for m in _messages(response.wsgi_request))

    def test_enable_backfill_refuses_a_team_of_another_organization(self) -> None:
        self._server()
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        with patch(f"{MW}.onboard_team") as mock_onboard:
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/enable-backfill/",
                {"team_id": str(other_team.id), "schema_name": "env_b", "reason": "Customer asked"},
            )

        assert response.status_code == 400
        mock_onboard.assert_not_called()
        assert "does not belong to organization" in response.content.decode()

    def test_deprovision_calls_helper_bypassing_flag(self) -> None:
        self._server()
        with patch(f"{MW}.deprovision", return_value=Response({"status": "ok"}, status=200)) as mock_deprovision:
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/deprovision/", {"reason": "Customer churned"}
            )

        assert response.status_code == 302
        mock_deprovision.assert_called_once_with(
            self.organization.id, require_enabled=False, triggered_by=f"django-admin:{self.user.email}"
        )

    def test_deprovision_needs_a_reason_and_get_does_not_call_helper(self) -> None:
        self._server()
        with patch(f"{MW}.deprovision") as mock_deprovision:
            form = self.client.get(f"{self.organization_url}managed-warehouse/deprovision/")
            refused = self.client.post(f"{self.organization_url}managed-warehouse/deprovision/", {})

        assert form.status_code == 200
        assert refused.status_code == 400
        mock_deprovision.assert_not_called()

    def test_deprovision_failure_shows_the_error_and_logs(self) -> None:
        self._server()
        with (
            patch(f"{MW}.deprovision", return_value=Response({"error": "still running"}, status=409)),
            patch("products.managed_warehouse.backend.logic.staff_actions.logger.warning") as mock_warning,
        ):
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/deprovision/", {"reason": "Customer churned"}
            )

        assert response.status_code == 409
        assert "Failed (status 409): still running" in response.content.decode()
        mock_warning.assert_called_once_with(
            "admin_managed_warehouse_action_failed",
            action=f"Deprovisioned managed warehouse for org {self.organization.id}",
            triggered_by=f"django-admin:{self.user.email}",
            status_code=409,
            error="still running",
        )

    @parameterized.expand([("enable-backfill",), ("deprovision",)])
    def test_old_action_urls_redirect_to_the_organization_panel(self, action: str) -> None:
        server = self._server()

        response = self.client.get(f"/admin/managed_warehouse/duckgresserver/{server.pk}/{action}/?from=bookmark")

        assert response.status_code == 302
        assert response["Location"] == f"{self.organization_url}managed-warehouse/{action}/?from=bookmark"

    def test_old_action_url_of_an_unknown_server_is_a_404(self) -> None:
        response = self.client.get(
            "/admin/managed_warehouse/duckgresserver/019f98c1-0000-0000-0000-000000000000/deprovision/"
        )

        assert response.status_code == 404
