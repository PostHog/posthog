from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite
from django.test import RequestFactory
from django.urls import reverse

from posthog.admin import register_all_admin
from posthog.models import Team

from products.warehouse_sources.backend.admin.data_warehouse_table_admin import DataWarehouseTableAdmin
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestDataWarehouseTableAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # is_superuser is a read-only alias for is_staff in this codebase (no separate superuser
        # concept), and Django's default auth backend grants every permission to a superuser.
        self.user.is_staff = True
        self.user.save()
        self.admin = DataWarehouseTableAdmin(DataWarehouseTable, AdminSite())

    def test_has_add_permission_is_false(self) -> None:
        # This form has no way to set a credential (see readonly_fields), so any table it created
        # would carry the same credential-less-plus-attacker-chosen-url_pattern combination
        # DataWarehouseTable.clean()/save() exist to refuse - and those checks can't cover creation,
        # since a brand-new row has no prior state to compare against. Blocking add here is the
        # closest equivalent for a surface that isn't the product's own controlled creation paths.
        request = RequestFactory().get("/")
        request.user = self.user

        assert self.admin.has_add_permission(request) is False

    def test_add_view_rejects_a_credential_less_table_pointed_at_another_teams_data(self) -> None:
        register_all_admin()
        self.client.force_login(self.user)
        add_url = reverse(f"admin:{DataWarehouseTable._meta.app_label}_{DataWarehouseTable._meta.model_name}_add")

        # row_count/size_in_s3_mib/columns are filled in so this is otherwise a fully valid
        # submission - without has_add_permission, it 302-redirects to the changelist and creates
        # the row (verified by temporarily reverting the fix locally), so the 403 below is coming
        # from the permission check this test exists to pin, not from incidental form invalidity.
        response = self.client.post(
            add_url,
            {
                "team": self.team.pk,
                "name": "attacker_table",
                "format": "CSVWithNames",
                "url_pattern": "https://s3.us-east-1.amazonaws.com/ph-warehouse/file_uploads/team_999/*.csv",
                "options": "{}",
                "row_count": "0",
                "size_in_s3_mib": "0",
                "columns": "{}",
            },
        )

        assert response.status_code == 403
        assert not DataWarehouseTable.objects.filter(name="attacker_table").exists()

    def test_change_view_does_not_move_a_table_to_another_team(self) -> None:
        register_all_admin()
        self.client.force_login(self.user)
        other_team = Team.objects.create(organization=self.organization)
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="customer_table",
            format="CSVWithNames",
            url_pattern="https://s3.us-east-1.amazonaws.com/customer-bucket/data/*.csv",
            credential=DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret"),
            columns={},
        )
        change_url = reverse(
            f"admin:{DataWarehouseTable._meta.app_label}_{DataWarehouseTable._meta.model_name}_change", args=[table.pk]
        )

        response = self.client.post(
            change_url,
            {
                "team": other_team.pk,
                "name": table.name,
                "format": table.format,
                "url_pattern": table.url_pattern,
                "options": "{}",
                "row_count": "0",
                "size_in_s3_mib": "0",
                "columns": "{}",
            },
        )

        assert response.status_code == 302
        table.refresh_from_db()
        assert table.team_id == self.team.pk
