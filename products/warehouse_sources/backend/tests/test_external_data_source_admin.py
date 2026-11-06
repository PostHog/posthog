import uuid
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.urls import reverse

from products.warehouse_sources.backend.admin.external_data_source_admin import ExternalDataSourceAdmin
from products.warehouse_sources.backend.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestExternalDataSourceAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        registered_admin = admin.site._registry.get(ExternalDataSource)
        assert isinstance(registered_admin, ExternalDataSourceAdmin)
        self.admin = cast(ModelAdmin, registered_admin)
        # Product-scoped test runs keep some third-party admins registered while excluding their
        # app URLs. The sidebar is unrelated to these model-admin assertions and cannot reverse
        # those deliberately absent app URLs.
        get_app_list_patcher = patch.object(admin.site, "get_app_list", return_value=[])
        get_app_list_patcher.start()
        self.addCleanup(get_app_list_patcher.stop)

    def _source(
        self,
        *,
        credential_kind: str,
        system_managed: bool | None = True,
        deleted: bool = False,
        job_inputs: dict[str, object] | None = None,
    ) -> ExternalDataSource:
        connection_metadata: dict[str, object] = {
            "credential_kind": credential_kind,
            "engine": "duckdb",
        }
        if system_managed is not None:
            connection_metadata["system_managed"] = system_managed
        return ExternalDataSource._base_manager.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix="managed_warehouse",
            deleted=deleted,
            job_inputs=job_inputs or {},
            connection_metadata=connection_metadata,
        )

    def test_admin_rejects_every_write_route(self) -> None:
        source = self._source(credential_kind="project_reader")
        self.client.force_login(self.user)

        add_response = self.client.post(reverse("admin:warehouse_sources_externaldatasource_add"), {})
        change_response = self.client.post(
            reverse("admin:warehouse_sources_externaldatasource_change", args=[source.pk]),
            {"description": "changed"},
        )
        delete_response = self.client.post(
            reverse("admin:warehouse_sources_externaldatasource_delete", args=[source.pk]),
            {"post": "yes"},
        )

        assert add_response.status_code == 403
        assert change_response.status_code == 403
        assert delete_response.status_code == 403
        source.refresh_from_db()
        assert source.description is None
        assert ExternalDataSource._base_manager.filter(pk=source.pk).exists()

    def test_change_view_never_renders_encrypted_job_inputs(self) -> None:
        source = self._source(
            credential_kind="org_root",
            job_inputs={"host": "warehouse.example.test", "password": "admin-secret-sentinel"},
        )
        metadata = source.connection_metadata
        assert isinstance(metadata, dict)
        source.connection_metadata = {
            **metadata,
            "private_marker": "metadata-secret-sentinel",
        }
        source.save(update_fields=["connection_metadata", "updated_at"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:warehouse_sources_externaldatasource_change", args=[source.pk]))

        assert response.status_code == 200
        assert b"Job inputs" not in response.content
        assert b"Connection metadata" not in response.content
        assert b"admin-secret-sentinel" not in response.content
        assert b"metadata-secret-sentinel" not in response.content
        assert "job_inputs" in response.context["original"].get_deferred_fields()

    def test_change_view_lists_only_this_sources_schemas(self) -> None:
        source = self._source(credential_kind="project_reader")
        other_source = self._source(credential_kind="project_reader")
        schema = ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="public.users")
        ExternalDataSchema.objects.create(team_id=self.team.pk, source=other_source, name="public.orders")
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:warehouse_sources_externaldatasource_change", args=[source.pk]))

        assert response.status_code == 200
        assert [listed.pk for listed in response.context["schema_page"].object_list] == [schema.pk]
        schema_url = reverse("admin:warehouse_sources_externaldataschema_change", args=[schema.pk])
        assert schema_url.encode() in response.content

    def test_pagination_links_keep_changelist_filters(self) -> None:
        source = self._source(credential_kind="project_reader")
        for name in ("public.users", "public.orders"):
            ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name=name)
        self.client.force_login(self.user)

        with patch.object(ExternalDataSourceAdmin, "SCHEMAS_PER_PAGE", 1):
            response = self.client.get(
                reverse("admin:warehouse_sources_externaldatasource_change", args=[source.pk]),
                {"_changelist_filters": "source_type=Postgres"},
            )

        assert response.status_code == 200
        assert b"_changelist_filters=source_type%3DPostgres&amp;page=2" in response.content

    def test_credential_kind_filter_uses_connection_metadata(self) -> None:
        project_reader = self._source(credential_kind="project_reader")
        dynamic = self._source(credential_kind="duckgres_service")
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("admin:warehouse_sources_externaldatasource_changelist"),
            {"credential_kind": "project_reader"},
        )

        assert response.status_code == 200
        result_ids = {source.pk for source in response.context["cl"].result_list}
        assert project_reader.pk in result_ids
        assert dynamic.pk not in result_ids
        assert all("job_inputs" in source.get_deferred_fields() for source in response.context["cl"].result_list)

    def test_system_managed_and_deleted_filters_can_find_historical_sources(self) -> None:
        historical = self._source(credential_kind="project_reader", deleted=True)
        self._source(credential_kind="project_reader", deleted=False)
        non_system_managed = self._source(credential_kind="org_root", system_managed=False, deleted=True)
        missing_system_managed = self._source(credential_kind="org_root", system_managed=None, deleted=True)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("admin:warehouse_sources_externaldatasource_changelist"),
            {"credential_kind": "project_reader", "system_managed": "yes", "deleted__exact": "1"},
        )

        assert response.status_code == 200
        assert [source.pk for source in response.context["cl"].result_list] == [historical.pk]

        non_system_response = self.client.get(
            reverse("admin:warehouse_sources_externaldatasource_changelist"),
            {"system_managed": "no", "deleted__exact": "1"},
        )
        assert non_system_response.status_code == 200
        assert {source.pk for source in non_system_response.context["cl"].result_list} == {
            non_system_managed.pk,
            missing_system_managed.pk,
        }
