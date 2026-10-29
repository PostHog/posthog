from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

import requests
import requests_mock
from parameterized import parameterized

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedSchema, TablePair
from products.warehouse_sources.backend.models import ExternalDataSchema, ExternalDataSource, PendingSourceCredential
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME as STRIPE_DISCOUNT_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_FACADE = "products.warehouse_sources.backend.facade.warehouse_migration"
_SERVICE = "products.warehouse_sources.backend.migration.service"


class TestWarehouseMigrationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch(f"{_FACADE}.is_migration_import_enabled", return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        start = patch(f"{_SERVICE}.start_crawl", return_value="warehouse-migration-crawl-test")
        self.start_crawl: MagicMock = start.start()
        self.addCleanup(start.stop)
        self.url = f"/api/projects/{self.team.pk}/warehouse_migrations/"

    def _migration(self) -> WarehouseMigration:
        return WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            created_by=self.user,
            provider=WarehouseMigration.Provider.FIVETRAN,
            status=WarehouseMigration.Status.READY,
            credentials={"api_key": "fake-key", "api_secret": "fake-secret"},
        )

    def _item(self, migration: WarehouseMigration, **overrides: Any) -> WarehouseMigrationItem:
        fields: dict[str, Any] = {
            "team_id": self.team.pk,
            "migration": migration,
            "vendor_connection_id": f"conn_{uuid4().hex[:8]}",
            "vendor_service": "hubspot",
            "name": "hubspot",
            "verdict": WarehouseMigrationItem.Verdict.AS_IS,
            **overrides,
        }
        return WarehouseMigrationItem.objects.for_team(self.team.pk).create(**fields)

    def test_flag_off_hides_the_endpoint(self) -> None:
        self.flag.return_value = False
        assert self.client.get(self.url).status_code == 404

    def _create(self, **mock: Any) -> Any:
        with requests_mock.Mocker() as m:
            m.get(f"{FIVETRAN_API_URL}/account/info", **mock)
            return self.client.post(
                self.url, {"provider": "fivetran", "api_key": "fake-key", "api_secret": "fake-secret"}
            )

    @parameterized.expand(
        [
            ("rejected_key", {"status_code": 401, "json": {"code": "AuthFailed", "message": "Unauthorized"}}),
            ("unreachable", {"exc": requests.ConnectionError}),
        ]
    )
    def test_create_refuses_a_key_fivetran_does_not_accept(self, _name: str, mock: dict[str, Any]) -> None:
        response = self._create(**mock)

        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "api_key"
        assert not WarehouseMigration.objects.for_team(self.team.pk).exists()
        self.start_crawl.assert_not_called()

    def test_create_stores_the_key_and_starts_the_crawl(self) -> None:
        def worker_starts_at_once(*, team_id: int, migration_id: Any) -> str:
            WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).update(
                status=WarehouseMigration.Status.CRAWLING
            )
            return "warehouse-migration-crawl-test"

        self.start_crawl.side_effect = worker_starts_at_once
        response = self._create(json={"code": "Success", "data": {"account_id": "acct_example"}})

        assert response.status_code == 201, response.json()
        assert "fake-secret" not in response.content.decode()
        migration = WarehouseMigration.objects.for_team(self.team.pk).get()
        assert migration.credentials == {"api_key": "fake-key", "api_secret": "fake-secret"}
        assert migration.workflow_id == "warehouse-migration-crawl-test"
        # The API must not write `pending` back over a crawl that already started.
        assert migration.status == WarehouseMigration.Status.CRAWLING
        self.start_crawl.assert_called_once_with(team_id=self.team.pk, migration_id=migration.id)

    def test_items_and_counts_follow_skips(self) -> None:
        migration = self._migration()
        pending = self._item(migration)
        self._item(migration, verdict=WarehouseMigrationItem.Verdict.UNSUPPORTED)
        applied = self._item(
            migration,
            status=WarehouseMigrationItem.Status.APPLIED,
            proposal=ItemProposal(
                source_type=ExternalDataSourceType.HUBSPOT,
                prefix="hubspot",
                prefill={},
                schemas=(ProposedSchema(name="contacts", should_sync=True, sync_type=None, vendor_table="contact"),),
                sync_frequency="6hour",
                sync_time_of_day=None,
                destination=None,
                inferred_tables=(TablePair(vendor_table="contact", posthog_table="contacts"),),
                unmatched_tables=("email_event",),
                unused_posthog_tables=("deals",),
            ).to_json(),
        )
        applying = self._item(migration, status=WarehouseMigrationItem.Status.APPLYING)

        skip = self.client.post(f"{self.url}{migration.id}/items/{pending.id}/skip/")
        assert skip.status_code == 200, skip.json()
        assert skip.json()["status"] == "skipped"
        for claimed in (applied, applying):
            assert self.client.post(f"{self.url}{migration.id}/items/{claimed.id}/skip/").status_code == 400

        detail = self.client.get(f"{self.url}{migration.id}/").json()
        assert "credentials" not in detail
        assert detail["item_counts"] == {"as_is": 1, "caveats": 0, "unsupported": 1, "applied": 1, "skipped": 1}
        items = self.client.get(f"{self.url}{migration.id}/items/").json()
        assert len(items) == 4
        (proposal,) = [item["proposal"] for item in items if item["proposal"]]
        assert proposal["inferred_tables"] == [{"vendor_table": "contact", "posthog_table": "contacts"}]
        assert proposal["unmatched_tables"] == ["email_event"]
        assert proposal["unused_posthog_tables"] == ["deals"]

    def test_items_list_survives_plans_stored_in_an_older_shape(self) -> None:
        migration = self._migration()
        # Saved before `alternative_names`, `vendor_table` and the table-match fields existed.
        old = {
            "source_type": "Hubspot",
            "prefix": "hubspot",
            "prefill": {},
            "schemas": [
                {"name": "contacts", "should_sync": True, "sync_type": None, "disabled_columns": [], "row_filters": []}
            ],
            "sync_frequency": "6hour",
            "sync_time_of_day": None,
            "destination": None,
        }
        self._item(migration, name="old", proposal=old)
        self._item(migration, name="broken", proposal={"source_type": "NotASource"})

        response = self.client.get(f"{self.url}{migration.id}/items/")

        assert response.status_code == 200, response.json()
        by_name = {item["name"]: item for item in response.json()}
        assert by_name["old"]["proposal"]["schemas"][0]["alternative_names"] == []
        assert by_name["old"]["proposal"]["inferred_tables"] == []
        assert by_name["broken"]["proposal"] is None
        assert any("Refresh the migration" in caveat for caveat in by_name["broken"]["caveats"])

    def test_bulk_skip_keeps_the_chosen_items_and_claimed_ones(self) -> None:
        migration = self._migration()
        keep = self._item(migration, name="keep")
        other = self._item(migration, name="other")
        failed = self._item(migration, name="failed", status=WarehouseMigrationItem.Status.FAILED)
        applying = self._item(migration, name="applying", status=WarehouseMigrationItem.Status.APPLYING)
        url = f"{self.url}{migration.id}/items/skip/"

        assert self.client.post(url, {}, format="json").status_code == 400
        both = {"item_ids": [str(other.id)], "keep_item_ids": [str(keep.id)]}
        assert self.client.post(url, both, format="json").status_code == 400

        response = self.client.post(url, {"keep_item_ids": [str(keep.id)]}, format="json")

        assert response.status_code == 200, response.json()
        assert sorted(response.json()["skipped_item_ids"]) == sorted([str(other.id), str(failed.id)])
        assert response.json()["not_skipped_item_ids"] == [str(applying.id)]
        statuses = dict(
            WarehouseMigrationItem.objects.for_team(self.team.pk)
            .filter(migration=migration)
            .values_list("name", "status")
        )
        assert statuses == {"keep": "pending", "other": "skipped", "failed": "skipped", "applying": "applying"}

    def test_list_pages_newest_first_without_repeating_tied_rows(self) -> None:
        oldest, *tied = (self._migration() for _ in range(3))
        WarehouseMigration.objects.for_team(self.team.pk).filter(id=oldest.id).update(
            created_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        WarehouseMigration.objects.for_team(self.team.pk).filter(id__in=[m.id for m in tied]).update(
            created_at=datetime(2026, 1, 2, tzinfo=UTC)
        )

        first = self.client.get(self.url, {"limit": 2}).json()
        second = self.client.get(self.url, {"limit": 2, "offset": 2}).json()

        assert first["count"] == 3
        assert first["next"] is not None
        assert {row["id"] for row in first["results"]} == {str(m.id) for m in tied}
        assert [row["id"] for row in second["results"]] == [str(oldest.id)]
        assert second["next"] is None

    def test_refresh_restarts_the_crawl_unless_one_is_running(self) -> None:
        migration = self._migration()
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 200
        self.start_crawl.assert_called_once()
        migration.refresh_from_db()
        assert migration.status == WarehouseMigration.Status.PENDING
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 400

    def test_a_crawl_that_cannot_start_fails_so_it_can_be_refreshed(self) -> None:
        migration = self._migration()
        self.start_crawl.side_effect = RuntimeError("temporal is down")

        response = self.client.post(f"{self.url}{migration.id}/refresh/")

        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "failed"
        self.start_crawl.side_effect = None
        assert self.client.post(f"{self.url}{migration.id}/refresh/").json()["status"] == "pending"

    def test_another_teams_migration_or_a_malformed_id_is_not_found(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        migration = WarehouseMigration.objects.for_team(other_team.pk).create(
            team_id=other_team.pk, provider=WarehouseMigration.Provider.FIVETRAN
        )
        own = self._migration()
        assert self.client.get(f"{self.url}{migration.id}/").status_code == 404
        # Hex-only, so they pass a loose route pattern and would reach `UUID()`.
        assert self.client.get(f"{self.url}abc/").status_code == 404
        assert self.client.post(f"{self.url}{own.id}/items/abc/skip/").status_code == 404


_STRIPE_VALID = patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
    return_value=(True, None),
)
_NO_PERSON_JOIN = patch(
    "products.warehouse_sources.backend.presentation.views.external_data_source.base.ensure_person_join"
)
_NO_VIEW_SYNC = patch(
    "products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views"
)
_APPLY_FLAG = f"{_FACADE}.is_migration_import_enabled"
_SOURCE_SETUP = "products.warehouse_sources.backend.presentation.views.external_data_source.source_setup"


class TestApplyMigrationItem(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for patcher in (patch(_APPLY_FLAG, return_value=True), _STRIPE_VALID, _NO_PERSON_JOIN, _NO_VIEW_SYNC):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.url = f"/api/projects/{self.team.pk}/external_data_sources/apply_migration_item/"
        migration = WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, provider=WarehouseMigration.Provider.FIVETRAN, status=WarehouseMigration.Status.READY
        )
        self.item = WarehouseMigrationItem.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            migration=migration,
            vendor_connection_id="conn_stripe",
            vendor_service="stripe",
            name="stripe_main",
            verdict=WarehouseMigrationItem.Verdict.CAVEATS,
            caveats=["planned caveat"],
            proposal=ItemProposal(
                source_type=ExternalDataSourceType.STRIPE,
                prefix="stripe_main",
                prefill={},
                schemas=(
                    ProposedSchema(name="Customer", should_sync=True, sync_type=None),
                    ProposedSchema(name="NotAStripeTable", should_sync=True, sync_type=None),
                ),
                sync_frequency="1hour",
                sync_time_of_day=None,
                destination=None,
            ).to_json(),
        )

    def _credential(self, user: Any = None) -> PendingSourceCredential:
        return PendingSourceCredential.objects.for_team(self.team.pk).create(
            team=self.team,
            source_type="Stripe",
            created_by=user or self.user,
            payload={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_stored"}},
        )

    def _apply(self, credential: PendingSourceCredential, **extra: str) -> Any:
        return self.client.post(self.url, {"item_id": str(self.item.id), "credential_id": str(credential.id), **extra})

    def test_creates_the_planned_source_once(self) -> None:
        credential = self._credential()
        response = self._apply(credential)
        assert response.status_code == 201, response.json()

        source = ExternalDataSource.objects.get(pk=response.json()["source_id"])
        assert source.prefix == "stripe_main"
        synced = ExternalDataSchema.objects.filter(source=source, should_sync=True)
        assert [schema.name for schema in synced] == ["Customer"]
        assert synced.get().sync_frequency_interval == timedelta(hours=1)
        assert not PendingSourceCredential.objects.for_team(self.team.pk).exists()

        self.item.refresh_from_db()
        assert self.item.status == WarehouseMigrationItem.Status.APPLIED
        assert self.item.external_data_source_id == source.id
        assert self.item.caveats[0] == "planned caveat"
        assert any("`NotAStripeTable`" in caveat for caveat in self.item.caveats)

        assert self._apply(self._credential()).status_code == 400
        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 1

    def test_another_users_credential_fails_the_item(self) -> None:
        other_user = self._create_user("other@example.com")
        response = self._apply(self._credential(user=other_user))

        assert response.status_code == 400
        assert not ExternalDataSource.objects.filter(team_id=self.team.pk).exists()
        self.item.refresh_from_db()
        assert self.item.status == WarehouseMigrationItem.Status.FAILED
        assert "not found or expired" in self.item.error

    def test_flag_off_hides_the_action(self) -> None:
        with patch(_APPLY_FLAG, return_value=False):
            assert self._apply(self._credential()).status_code == 404

    def test_connect_link_carries_the_item_for_prefill(self) -> None:
        url = f"/api/projects/{self.team.pk}/external_data_sources/connect_link/"
        response = self.client.get(url, {"source_type": "Stripe", "migration_item_id": str(self.item.id)})
        assert response.status_code == 200, response.json()
        assert (
            f"migration_id={self.item.migration_id}&migration_item_id={self.item.id}" in response.json()["connect_url"]
        )

        other_team = self.create_team_with_organization(organization=self.organization)
        other_item = WarehouseMigrationItem.objects.for_team(other_team.pk).create(
            team_id=other_team.pk,
            migration=WarehouseMigration.objects.for_team(other_team.pk).create(
                team_id=other_team.pk, provider="fivetran"
            ),
            vendor_connection_id="conn_other",
            vendor_service="stripe",
            name="other",
            verdict=WarehouseMigrationItem.Verdict.AS_IS,
        )
        response = self.client.get(url, {"source_type": "Stripe", "migration_item_id": str(other_item.id)})
        assert response.status_code == 400

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook",
        return_value=WebhookCreationResult(success=True, extra_inputs={"signing_secret": "whsec_fake"}),
    )
    def test_webhook_turns_on_only_planned_tables(self, _create_webhook: MagicMock) -> None:
        HogFunctionTemplate.objects.create(
            template_id="template-warehouse-source-stripe",
            name="Stripe warehouse source webhook",
            code="// test code",
            code_language="hog",
            inputs_schema=[
                {"type": "string", "key": "signing_secret", "label": "Signing secret", "secret": True},
                {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True},
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True},
            ],
            type="warehouse_source_webhook",
            status="alpha",
            category=[],
        )

        response = self._apply(self._credential())

        assert response.status_code == 201, response.json()
        schemas = ExternalDataSchema.objects.filter(source_id=response.json()["source_id"])
        assert schemas.get(name=STRIPE_CUSTOMER_RESOURCE_NAME).sync_type == ExternalDataSchema.SyncType.WEBHOOK
        # Webhook-only and not in the plan, so the webhook must not turn it on.
        assert schemas.get(name=STRIPE_DISCOUNT_RESOURCE_NAME).should_sync is False

    @parameterized.expand([("stale_claim", 20, 201), ("live_claim", 1, 400)])
    def test_only_a_stale_claim_can_be_taken_over(self, _name: str, minutes_ago: int, expected_status: int) -> None:
        WarehouseMigrationItem.objects.for_team(self.team.pk).filter(id=self.item.id).update(
            status=WarehouseMigrationItem.Status.APPLYING, updated_at=timezone.now() - timedelta(minutes=minutes_ago)
        )

        assert self._apply(self._credential()).status_code == expected_status

    @parameterized.expand(
        [
            ("pending_item_fails", WarehouseMigrationItem.Status.PENDING, WarehouseMigrationItem.Status.FAILED),
            (
                "applied_item_stays_applied",
                WarehouseMigrationItem.Status.APPLIED,
                WarehouseMigrationItem.Status.APPLIED,
            ),
        ]
    )
    def test_an_invalid_stored_plan_fails_only_a_claimable_item(
        self, _name: str, status: str, expected_status: str
    ) -> None:
        WarehouseMigrationItem.objects.for_team(self.team.pk).filter(id=self.item.id).update(
            status=status, proposal={"source_type": "NotASource"}
        )

        assert self._apply(self._credential()).status_code == 400
        self.item.refresh_from_db()
        assert self.item.status == expected_status

    def test_table_overrides_change_the_created_tables(self) -> None:
        bad = {"table_overrides": [{"vendor_table": "not_a_table", "posthog_table": "Invoice"}]}
        response = self.client.post(
            self.url,
            {"item_id": str(self.item.id), "credential_id": str(self._credential().id), **bad},
            format="json",
        )
        assert response.status_code == 400
        self.item.refresh_from_db()
        assert self.item.status == WarehouseMigrationItem.Status.PENDING

        overrides = {"table_overrides": [{"vendor_table": "NotAStripeTable", "posthog_table": "Invoice"}]}
        response = self.client.post(
            self.url,
            {"item_id": str(self.item.id), "credential_id": str(self._credential().id), **overrides},
            format="json",
        )

        assert response.status_code == 201, response.json()
        synced = ExternalDataSchema.objects.filter(source_id=response.json()["source_id"], should_sync=True)
        assert sorted(schema.name for schema in synced) == ["Customer", "Invoice"]

    def test_a_source_created_before_a_failure_is_linked_not_created_again(self) -> None:
        # Raises after the source row exists, as revenue view setup or a database error can.
        with patch(f"{_SOURCE_SETUP}.report_user_action", side_effect=RuntimeError("after create")):
            assert self._apply(self._credential()).status_code == 500

        source = ExternalDataSource.objects.get(team_id=self.team.pk)
        self.item.refresh_from_db()
        assert (self.item.status, self.item.external_data_source_id) == (
            WarehouseMigrationItem.Status.APPLIED,
            source.id,
        )
        assert any("failed partway" in caveat for caveat in self.item.caveats), self.item.caveats

        # A retry with another prefix must not create a second source.
        assert self._apply(self._credential(), prefix="stripe_retry").status_code == 400
        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 1

    @parameterized.expand([("source_with_tables", True), ("source_without_tables", False)])
    def test_a_retry_after_a_dead_apply_links_the_source_it_created(self, _name: str, has_tables: bool) -> None:
        claimed_at = timezone.now() - timedelta(minutes=20)
        WarehouseMigrationItem.objects.for_team(self.team.pk).filter(id=self.item.id).update(
            status=WarehouseMigrationItem.Status.APPLYING,
            updated_at=claimed_at,
            claimed_at=claimed_at,
            claimed_prefix="stripe_main",
        )
        orphan = ExternalDataSource.objects.create(
            team=self.team,
            source_id="fake-source",
            connection_id="fake-connection",
            source_type=ExternalDataSourceType.STRIPE,
            prefix="stripe_main",
            description="Imported from the migrated connection stripe_main.",
        )
        if has_tables:
            ExternalDataSchema.objects.create(team=self.team, source=orphan, name="Customer", should_sync=True)

        response = self._apply(self._credential())

        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 1
        self.item.refresh_from_db()
        if has_tables:
            assert response.status_code == 201, response.json()
            assert response.json()["source_id"] == str(orphan.id)
            assert (self.item.status, self.item.external_data_source_id) == (
                WarehouseMigrationItem.Status.APPLIED,
                orphan.id,
            )
        else:
            # A source with no tables never syncs, so the user deletes it rather than having it linked.
            assert response.status_code == 400
            assert "Delete that source" in response.json()["message"]
            assert self.item.status == WarehouseMigrationItem.Status.FAILED
