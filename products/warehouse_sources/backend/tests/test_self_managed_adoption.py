from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql.database.database import Database

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.testing import add_role_member, create_access_control, create_role
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, self_managed_table_ref
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.self_managed_access import (
    ADOPTION_ACCESS_ERROR,
    PROJECT_RULES_REASON,
    ROLES_REASON,
    TABLE_RULES_REASON,
    AdoptionAccessError,
    TeamAccessRules,
    assert_adoption_keeps_access,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    find_replaced_self_managed_table,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    self_managed_adoption_error,
)
from products.warehouse_sources.backend.test.self_managed import link_self_managed_table
from products.warehouse_sources.backend.types import DataWarehouseTableFormat

SOURCE_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_source"
SCHEMA_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_schema"
EXPORTS_URL = "https://exports.s3.eu-west-1.amazonaws.com/orders/*.csv"
UPLOAD_DOMAIN = "warehouse.example.com"
UPLOAD_BUCKET = "ph-warehouse"
UPLOAD_ID = "11111111-2222-4333-8444-555555555555"

_LEVELS = ("none", "viewer", "editor", "manager")
_ROLE_NAMES = ("A", "B")
# Each member stands for one way a member can relate to the rules.
_MEMBERS: dict[str, tuple[tuple[str, ...], OrganizationMembership.Level]] = {
    "plain": ((), OrganizationMembership.Level.MEMBER),
    "named": ((), OrganizationMembership.Level.MEMBER),
    "in_role": (("A",), OrganizationMembership.Level.MEMBER),
    "named_in_roles": (("A", "B"), OrganizationMembership.Level.MEMBER),
    "in_both_roles": (("A", "B"), OrganizationMembership.Level.MEMBER),
    "admin": ((), OrganizationMembership.Level.ADMIN),
    "project_admin": ((), OrganizationMembership.Level.MEMBER),
    "creator": ((), OrganizationMembership.Level.MEMBER),
}
# Where a rule can be: "<scope>" is the scope's default rule, "<scope>:<member or role>" names a subject.
_SCOPES = {
    "table": ("warehouse_table", True),
    "warehouse": ("warehouse_objects", False),
    "sources": ("external_data_source", False),
    # Resolution reads the rules for all warehouse tables from warehouse_objects, so this rule never applies.
    "all_tables": ("warehouse_table", False),
}


class _SelfManagedTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            access_key="AKIAFIRST", access_secret="c2VjcmV0", team=self.team
        )

    def _table(self, name: str = "orders", url: str = EXPORTS_URL, **fields: Any) -> DataWarehouseTable:
        fields.setdefault("credential", self.credential)
        return DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTableFormat.CSVWithNames,
            url_pattern=url,
            team=self.team,
            columns={"Order ID": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True}},
            options={"csv_allow_double_quotes": True},
            **fields,
        )

    def _adopt(self, table: DataWarehouseTable, schema: ExternalDataSchema) -> None:
        table.refresh_from_db()
        table.adopt_into_source(schema.source)
        table.url_pattern = f"https://bucket.s3.amazonaws.com/team_{self.team.pk}/{table.name}"
        table.format = DataWarehouseTableFormat.DeltaS3Wrapper
        table.save(internally_computed_url_pattern=True)
        schema.table = table
        schema.save()


class TestAdoptedTableName(_SelfManagedTest):
    def test_an_adopted_table_is_queried_by_its_bare_name_before_and_after(self) -> None:
        table = self._table("orders_raw")
        schema = link_self_managed_table(table)

        before = Database.create_for(team=self.team)
        assert before.has_table("orders_raw")
        assert not before.has_table("amazons3.orders_raw")

        self._adopt(table, schema)

        after = Database.create_for(team=self.team)
        assert after.has_table("orders_raw")
        assert after.has_table("amazons3.orders_raw")


class TestDeletingAMigrationSchema(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patches = [
            patch(f"{SOURCE_VIEWS}.base.bulk_delete_external_data_schedules", return_value=[]),
            patch(f"{SOURCE_VIEWS}.base.delete_external_data_schedule"),
            patch(f"{SOURCE_VIEWS}.base.delete_discover_schemas_schedule"),
            patch(f"{SCHEMA_VIEWS}.external_data_workflow_exists", return_value=False),
            patch("products.data_warehouse.backend.s3.get_s3_client"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.credential = DataWarehouseCredential.objects.create(
            access_key="AKIAFIRST", access_secret="c2VjcmV0", team=self.team
        )

    @parameterized.expand([("source",), ("schema",), ("schema_data",)])
    def test_deleting_before_the_first_sync_keeps_the_table_and_ends_its_migration(self, path: str) -> None:
        table = DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTableFormat.CSVWithNames,
            url_pattern=EXPORTS_URL,
            team=self.team,
            credential=self.credential,
        )
        schema = link_self_managed_table(table)
        urls = {
            "source": f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}",
            "schema": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}",
            "schema_data": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}/delete_data",
        }

        response = self.client.delete(urls[path])

        assert response.status_code in (200, 204), response.content
        table.refresh_from_db()
        assert (table.deleted, table.credential_id, table.url_pattern) == (False, self.credential.pk, EXPORTS_URL)
        assert Database.create_for(team=self.team).has_table("orders")
        schema = ExternalDataSchema.objects.select_related("source").get(pk=schema.pk)
        still_migrating = not schema.deleted and not schema.source.deleted
        assert still_migrating is (path == "schema_data")
        if still_migrating:
            ref = self_managed_table_ref(schema)
            assert ref is not None and ref.table_id == str(table.id)
            assert find_replaced_self_managed_table(schema, schema.source) == table


class _AccessRulesTest(_SelfManagedTest):
    def setUp(self) -> None:
        super().setUp()
        self._enable_access_control()
        self.roles = {
            name: create_role(organization_id=self.organization.id, name=f"Role {name}") for name in _ROLE_NAMES
        }
        self.users: dict[str, User] = {}
        self.memberships: dict[str, OrganizationMembership] = {}
        for name, (roles, level) in _MEMBERS.items():
            user = User.objects.create_and_join(self.organization, f"{name}@example.com", None, level=level)
            self.users[name] = user
            self.memberships[name] = OrganizationMembership.objects.get(user=user, organization=self.organization)
            for role in roles:
                add_role_member(role_id=self.roles[role], user_id=user.id)
        create_access_control(
            team_id=self.team.pk,
            resource="project",
            resource_id=str(self.team.pk),
            access_level="admin",
            organization_member_id=self.memberships["project_admin"].id,
        )

    def _enable_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()

    def _rule(self, slot: str, level: str, table: DataWarehouseTable | None = None) -> None:
        scope, _, subject = slot.partition(":")
        resource, on_table = _SCOPES[scope]
        create_access_control(
            team_id=self.team.pk,
            resource=resource,
            resource_id=str(table.id) if on_table and table is not None else None,
            access_level=level,
            organization_member_id=self.memberships[subject].id if subject in self.memberships else None,
            role_id=self.roles[subject] if subject in self.roles else None,
        )

    def _apply(self, rules: dict[str, str], table: DataWarehouseTable) -> None:
        for slot, level in rules.items():
            self._rule(slot, level, table)

    def _access(self, obj: Any) -> dict[str, str | None]:
        result: dict[str, str | None] = {
            name: UserAccessControl(user, self.team).get_user_access_level(obj) for name, user in self.users.items()
        }
        asker = UserAccessControl(self.users["admin"], self.team)
        for name, role_id in self.roles.items():
            result[f"role {name}"] = SubjectAccessControl.for_role(
                asker, self.team, str(role_id)
            ).get_user_access_level(obj)
        result["everyone"] = SubjectAccessControl.for_default(asker, self.team).get_user_access_level(obj)
        return result

    def _in_both_orders(self, obj: Any) -> dict[bool, dict[str, str | None]]:
        by_order = {}
        for most_specific in (False, True):
            self.organization.uses_most_specific_access_resolution = most_specific
            self.organization.save()
            by_order[most_specific] = self._access(obj)
        return by_order

    def _source_rules(self, source: ExternalDataSource) -> set[tuple[str, str]]:
        names = {str(m.id): name for name, m in self.memberships.items()} | {str(r): n for n, r in self.roles.items()}
        return {
            (names.get(str(rule.organization_member_id or rule.role_id or ""), ""), rule.access_level)
            for rule in AccessControl.objects.filter(
                team=self.team, resource="external_data_source", resource_id=str(source.pk)
            )
        }

    def _assert_adoption_keeps_access(self, table: DataWarehouseTable, schema: ExternalDataSchema) -> None:
        before = self._in_both_orders(table)
        assert_adoption_keeps_access(table, schema.source)
        self._adopt(table, schema)
        table.refresh_from_db()
        assert table.external_data_source_id == schema.source_id
        after = self._in_both_orders(table)
        on_source = self._in_both_orders(schema.source)
        assert after == before
        for most_specific, levels in on_source.items():
            for subject, level in levels.items():
                table_level = after[most_specific][subject]
                assert level is not None and table_level is not None
                assert _LEVELS.index(level) <= _LEVELS.index(table_level), (most_specific, subject, level, table_level)

    def _linked(self, rules: dict[str, str], name: str = "orders") -> tuple[DataWarehouseTable, ExternalDataSchema]:
        table = self._table(name, url=f"https://exports.s3.eu-west-1.amazonaws.com/{name}/*.csv")
        self._apply(rules, table)
        return table, link_self_managed_table(table)


class TestAdoptionKeepsAccess(_AccessRulesTest):
    @parameterized.expand(
        [
            ("no_rules", {}, set()),
            ("table_private", {"table": "none"}, {("", "none")}),
            ("table_read_only", {"table": "viewer"}, {("", "viewer")}),
            ("table_hidden_from_a_member", {"table:named": "none"}, {("named", "none")}),
            (
                "table_private_but_shared_with_a_member",
                {"table": "none", "table:named": "editor"},
                {("named", "editor"), ("", "none")},
            ),
            ("table_rule_for_a_role", {"table:A": "viewer"}, {("A", "viewer")}),
            (
                "member_rule_and_role_rule_for_one_member",
                {"table:named_in_roles": "viewer", "table:A": "editor", "table:B": "none"},
                {("named_in_roles", "viewer"), ("A", "editor"), ("B", "none")},
            ),
            ("warehouse_read_only", {"warehouse": "viewer"}, {("", "viewer")}),
            ("warehouse_hidden", {"warehouse": "none"}, {("", "none")}),
            ("warehouse_managers", {"warehouse": "manager"}, set()),
            # The table gives more than the default for sources, so the source must grant it.
            ("sources_read_only", {"sources": "viewer"}, {("", "editor")}),
            # The table gives less than the default for sources, so the source must be restricted.
            ("private_table_and_sources_open", {"table": "none", "sources": "editor"}, {("", "none")}),
            ("private_table_and_warehouse_read_only", {"table": "none", "warehouse": "viewer"}, {("", "none")}),
            ("rule_for_all_tables_never_applies", {"all_tables": "none"}, set()),
            ("rule_for_the_project_admin", {"table:project_admin": "none"}, {("project_admin", "none")}),
            ("rule_for_the_creator", {"table:creator": "none"}, {("creator", "none")}),
        ]
    )
    def test_adoption_keeps_every_subjects_access(
        self, _name: str, rules: dict[str, str], source_rules: set[tuple[str, str]]
    ) -> None:
        table = self._table(created_by=self.users["creator"])
        self._apply(rules, table)
        before = self._in_both_orders(table)

        schema = link_self_managed_table(table)

        assert self._source_rules(schema.source) == source_rules
        # Until the first sync the table has no source, so the source's rules don't reach it.
        assert self._in_both_orders(table) == before
        self._assert_adoption_keeps_access(table, schema)

    @parameterized.expand(
        [
            (f"table_{table}_warehouse_{warehouse}_sources_{sources}", table, warehouse, sources)
            for table in (None, *_LEVELS[:3])
            for warehouse in (None, *_LEVELS[:3])
            for sources in (None, *_LEVELS[:3])
        ]
    )
    def test_every_adoption_of_a_table_with_explicit_rules_keeps_access(
        self, _name: str, table_default: str | None, warehouse: str | None, sources: str | None
    ) -> None:
        table = self._table(created_by=self.users["creator"])
        rules = {"table:named": "viewer", "table:B": "none"}
        for slot, level in (("table", table_default), ("warehouse", warehouse), ("sources", sources)):
            if level is not None:
                rules[slot] = level
        self._apply(rules, table)

        plan = TeamAccessRules(self.team.pk).plan_for(str(table.id))

        if isinstance(plan, str):
            assert plan in (TABLE_RULES_REASON, PROJECT_RULES_REASON)
            return
        self._assert_adoption_keeps_access(table, link_self_managed_table(table))

    def test_rules_that_never_apply_are_not_copied(self) -> None:
        other_organization = Organization.objects.create(name="Elsewhere")
        foreign_role = create_role(organization_id=other_organization.id, name="Foreign")
        table = self._table()
        create_access_control(
            team_id=self.team.pk,
            resource="warehouse_table",
            resource_id=str(table.id),
            access_level="none",
            role_id=foreign_role,
        )
        before = self._in_both_orders(table)

        schema = link_self_managed_table(table)

        assert self._source_rules(schema.source) == set()
        assert self._in_both_orders(table) == before
        self._assert_adoption_keeps_access(table, schema)

    def test_a_rule_for_an_inactive_member_is_kept_on_the_source(self) -> None:
        User.objects.filter(pk=self.users["named"].pk).update(is_active=False)
        table = self._table()
        self._rule("table:named", "manager", table)

        schema = link_self_managed_table(table)

        assert self._source_rules(schema.source) == {("named", "manager")}
        assert_adoption_keeps_access(table, schema.source)

    def test_rules_of_an_organization_without_access_control_still_hold_when_it_comes_back(self) -> None:
        table = self._table()
        self._apply({"table": "none", "table:named": "viewer"}, table)
        with_access_control = self._in_both_orders(table)
        self.organization.available_product_features = []
        self.organization.save()

        schema = link_self_managed_table(table)

        assert self._source_rules(schema.source) == {("named", "viewer"), ("", "none")}
        self._assert_adoption_keeps_access(table, schema)
        self._enable_access_control()
        assert self._in_both_orders(table) == with_access_control

    def test_an_uploaded_table_keeps_its_access_on_its_own_source(self) -> None:
        with override_settings(DATAWAREHOUSE_BUCKET=UPLOAD_BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=UPLOAD_DOMAIN):
            table = self._table(
                "uploaded",
                url=f"https://{UPLOAD_DOMAIN}/file_uploads/team_{self.team.pk}/{UPLOAD_ID}/orders.csv",
                created_by=self.users["creator"],
                credential=None,
            )
            DataWarehouseTable.raw_objects.filter(pk=table.pk).update(options={"csv_allow_double_quotes": False})
            table.refresh_from_db()
            self._apply({"table": "none", "table:A": "viewer"}, table)

            schema = link_self_managed_table(table)

        assert schema.source.source_type == "FileUpload"
        assert self._source_rules(schema.source) == {("A", "viewer"), ("", "none")}
        self._assert_adoption_keeps_access(table, schema)


class TestAdoptionRefusesChangedRules(_AccessRulesTest):
    @parameterized.expand(
        [
            # A grant on a source can't widen "none" for all sources under most-specific resolution.
            ("sources_hidden", {"sources": "none"}, "access rules for sources"),
            ("sources_hidden_from_a_member", {"sources:named": "none"}, "access rules for sources"),
            ("table_read_only_and_sources_hidden", {"table": "viewer", "sources": "none"}, "access rules for sources"),
            # Everyone could manage the source, and through its rules change the table's access.
            ("sources_managed_by_everyone", {"sources": "manager"}, "access rules for sources"),
            # Members of one role see more of the warehouse than the others, and one default can't say that.
            ("warehouse_open_to_a_role", {"warehouse": "viewer", "warehouse:A": "editor"}, "access rules for sources"),
            ("warehouse_hidden_from_a_member", {"warehouse:named": "none"}, "access rules for sources"),
            (
                "table_rule_and_sources_hidden_from_a_role",
                {"table:named": "viewer", "sources:A": "none"},
                "access rules for sources",
            ),
            ("unknown_level", {"table": "superuser"}, "the level 'superuser'"),
        ]
    )
    def test_adoption_refuses_rules_no_source_rules_can_keep(
        self, _name: str, rules: dict[str, str], reason: str
    ) -> None:
        table, schema = self._linked({})
        self._apply(rules, table)

        with self.assertRaisesRegex(AdoptionAccessError, reason):
            assert_adoption_keeps_access(table, schema.source)

    def test_adoption_refuses_rules_that_name_too_many_roles(self) -> None:
        table, schema = self._linked({})
        for i in range(11):
            role = create_role(organization_id=self.organization.id, name=f"Extra {i}")
            create_access_control(
                team_id=self.team.pk,
                resource="warehouse_table",
                resource_id=str(table.id),
                access_level=_LEVELS[i % 4],
                role_id=role,
            )
            create_access_control(
                team_id=self.team.pk, resource="warehouse_objects", access_level=_LEVELS[i // 4], role_id=role
            )

        with self.assertRaisesRegex(AdoptionAccessError, ROLES_REASON):
            assert_adoption_keeps_access(table, schema.source)

    @parameterized.expand(
        [
            ("no_change", None, None),
            ("table_rule_added", "table:named", "the access rules of the table or of its source changed"),
            ("table_rule_widened", "table", "the access rules of the table or of its source changed"),
            ("source_rule_edited", "source", "the access rules of the table or of its source changed"),
            ("sources_hidden", "sources", "now the project has access rules for sources"),
        ]
    )
    def test_the_first_sync_refuses_to_adopt_a_table_whose_rules_changed(
        self, _name: str, change: str | None, refusal: str | None
    ) -> None:
        table, schema = self._linked({"table": "viewer"})
        if change == "table:named":
            self._rule("table:named", "viewer", table)
        elif change == "table":
            AccessControl.objects.filter(resource="warehouse_table", resource_id=str(table.id)).update(
                access_level="editor"
            )
        elif change == "source":
            AccessControl.objects.filter(resource="external_data_source", resource_id=str(schema.source_id)).update(
                access_level="none"
            )
        elif change == "sources":
            self._rule("sources", "none")

        if refusal is None:
            assert_adoption_keeps_access(table, schema.source)
            return
        with self.assertRaisesRegex(AdoptionAccessError, refusal):
            assert_adoption_keeps_access(table, schema.source)

    @parameterized.expand([("unchanged", False, False), ("rule_added", True, False), ("already_adopted", True, True)])
    def test_the_import_stops_before_extraction_only_when_the_rules_no_longer_fit(
        self, _name: str, rule_added: bool, adopted: bool
    ) -> None:
        table, schema = self._linked({"table": "viewer"})
        if rule_added:
            self._rule("table:named", "viewer", table)
        if adopted:
            self._adopt(table, schema)
            ExternalDataSchema.objects.filter(pk=schema.pk).update(table=None)
            schema.refresh_from_db()

        error = self_managed_adoption_error(schema)

        if not rule_added or adopted:
            assert error is None
            return
        assert error is not None
        assert error.startswith(f"{ADOPTION_ACCESS_ERROR} 'orders', because the access rules of the table")
        assert "an organization admin must make the access rules of this source the same" in error
