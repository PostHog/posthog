from posthog.test.base import BaseTest
from unittest.mock import patch

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
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseSourceLifecycle,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)

MW = "products.managed_warehouse.backend.presentation.views"
START_JOB = "products.managed_warehouse.backend.logic.view_translation_staff._start_translation_job"


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _messages(request) -> list[str]:
    return [str(m) for m in get_messages(request)]


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
        assert "Provision warehouse" in response.content.decode()
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
        assert "Provision warehouse" in content

    def _provision(self, team_id: int, **extra: str):
        url = f"{self.organization_url}managed-warehouse/provision/"
        form = {
            "team_id": str(team_id),
            "database_name": "my-warehouse",
            "schema_name": "prod_events",
            "reason": "Customer onboarding",
            **extra,
        }
        preview = self.client.post(url, form)
        if preview.status_code != 200:
            return preview, None
        return preview, self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

    @parameterized.expand([("customer", False), ("internal_testing", True)])
    def test_provision_shows_the_root_password_once_after_a_preview(self, _name: str, internal_only: bool) -> None:
        body = {"username": "root", "password": "example-root-password"}
        with patch(f"{MW}.provision", return_value=Response(body, status=202)) as mock_provision:
            preview, confirmed = self._provision(self.team.id, **({"internal_only": "on"} if internal_only else {}))
            assert confirmed is not None
            result = self.client.get(confirmed["Location"])

        assert "my-warehouse.dw." in preview.content.decode()
        mock_provision.assert_called_once_with(
            self.organization.id,
            "my-warehouse",
            self.team.id,
            "prod_events",
            require_enabled=False,
            triggered_by=f"django-admin:{self.user.email}",
            internal_only=internal_only,
        )
        assert confirmed.status_code == 302
        assert "example-root-password" in result.content.decode()
        assert all("example-root-password" not in m for m in _messages(result.wsgi_request))

    def test_provision_failure_shows_the_error_on_the_form(self) -> None:
        with patch(f"{MW}.provision", return_value=Response({"error": "nope"}, status=400)):
            _, confirmed = self._provision(self.team.id)

        assert confirmed is not None
        assert confirmed.status_code == 400
        assert "Failed (status 400): nope" in confirmed.content.decode()

    def test_provision_refuses_a_team_of_another_organization_in_the_preview(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        with patch(f"{MW}.provision") as mock_provision:
            preview, confirmed = self._provision(other_team.id)

        assert preview.status_code == 400
        assert confirmed is None
        mock_provision.assert_not_called()
        assert "does not belong to organization" in preview.content.decode()

    @parameterized.expand(
        [
            ("duckgresserver/provision/", "Provisioning a managed warehouse moved"),
            ("managedwarehouseviewtranslationjob/add/", "Starting a view translation job moved"),
        ]
    )
    def test_old_page_urls_point_to_the_console(self, old_path: str, message: str) -> None:
        response = self.client.get(f"/admin/managed_warehouse/{old_path}")

        assert response.status_code == 302
        assert response["Location"] == "/admin/console/"
        assert any(message in m for m in _messages(response.wsgi_request))

    def _saved_query(self, name: str, team: Team | None = None) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=team or self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )

    @parameterized.expand([("entire_organization", False), ("selected_views", True)])
    def test_start_view_translation_dispatches_a_job_after_commit(self, scope: str, select_views: bool) -> None:
        self._server()
        saved_query = self._saved_query("selected_view")
        view_ids = f"{saved_query.id},\n{saved_query.id}" if select_views else ""

        with patch(START_JOB) as start_job, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/start-view-translation/", {"saved_query_ids": view_ids}
            )

        assert response.status_code == 302
        job = ManagedWarehouseViewTranslationJob.objects.get()
        assert job.created_by == self.user
        assert job.trigger_source == ManagedWarehouseViewTranslationJob.TriggerSource.ADMIN
        assert job.status == ManagedWarehouseViewTranslationJob.Status.PENDING
        assert job.scope == scope
        assert job.selected_saved_query_ids == ([str(saved_query.id)] if select_views else [])
        start_job.assert_called_once_with(job.id, self.organization.id)

    @parameterized.expand([("not_a_uuid", "Enter valid view IDs"), ("other_org", "do not identify an active view")])
    def test_start_view_translation_refuses_views_outside_the_organization(self, case: str, error: str) -> None:
        self._server()
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        view_ids = "not-a-uuid" if case == "not_a_uuid" else str(self._saved_query("foreign", other_team).id)

        with patch(START_JOB) as start_job:
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/start-view-translation/", {"saved_query_ids": view_ids}
            )

        assert response.status_code == 400
        assert error in response.content.decode()
        assert not ManagedWarehouseViewTranslationJob.objects.exists()
        start_job.assert_not_called()

    def test_retry_view_translation_starts_a_job_for_failed_and_stale_views_then_hides_both_operations(self) -> None:
        self._server()
        saved_queries = [self._saved_query(name) for name in ["failed_view", "stale_view", "compiled_view"]]
        source_job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization,
            status=ManagedWarehouseViewTranslationJob.Status.COMPLETED_WITH_ERRORS,
        )
        for saved_query, status in zip(
            saved_queries,
            [
                ManagedWarehouseViewTranslationResult.Status.FAILED,
                ManagedWarehouseViewTranslationResult.Status.STALE,
                ManagedWarehouseViewTranslationResult.Status.COMPILED,
            ],
            strict=True,
        ):
            ManagedWarehouseViewTranslationResult.all_teams.create(
                job=source_job,
                team=self.team,
                saved_query_id=saved_query.id,
                saved_query_name=saved_query.name,
                source_query_hash="0" * 64,
                status=status,
            )
        assert "Retry failed view translations" in self.client.get(self.organization_url).content.decode()

        with patch(START_JOB) as start_job, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"{self.organization_url}managed-warehouse/retry-view-translation/", {"job_id": str(source_job.id)}
            )

        assert response.status_code == 302
        retry_job = ManagedWarehouseViewTranslationJob.objects.exclude(id=source_job.id).get()
        assert retry_job.trigger_source == ManagedWarehouseViewTranslationJob.TriggerSource.RETRY
        assert retry_job.scope == ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS
        assert retry_job.retry_of == source_job
        assert set(retry_job.selected_saved_query_ids) == {str(saved_query.id) for saved_query in saved_queries[:2]}
        start_job.assert_called_once_with(retry_job.id, self.organization.id)
        content = self.client.get(self.organization_url).content.decode()
        assert "Start view translation" not in content and "Retry failed view translations" not in content

        ManagedWarehouseViewTranslationJob.objects.filter(id=retry_job.id).update(
            status=ManagedWarehouseViewTranslationJob.Status.COMPLETED
        )
        content = self.client.get(self.organization_url).content.decode()
        assert "Start view translation" in content and "Retry failed view translations" not in content

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
