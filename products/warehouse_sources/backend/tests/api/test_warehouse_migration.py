import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

import requests
import requests_mock
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
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
_VIEW = "products.warehouse_sources.backend.presentation.views.warehouse_migration"
_SNAPSHOT = "products.warehouse_sources.backend.migration.fivetran.snapshot"


def _envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": "Success", "data": data}


_FLOAT_OVERFLOW = "float-overflow-placeholder"


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(depth):
        value = {"child": value}
    return value


def _fivetran_connection(connection_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": connection_id,
        "group_id": "grp_example",
        "service": "hubspot",
        "schema": connection_id,
        "schedule": {"schedule_type": "INTERVAL", "interval": 360},
        "config": {"api_key": "fake-unmasked-key", "account_name": "example"},
        **overrides,
    }


class TestWarehouseMigrationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch(f"{_FACADE}.is_migration_import_enabled", return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        start = patch(f"{_SERVICE}.start_crawl")
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
        def worker_starts_at_once(*, team_id: int, migration_id: Any, workflow_id: str) -> None:
            # A crawl writes only when the migration already names it.
            WarehouseMigration.objects.for_team(team_id).filter(id=migration_id, workflow_id=workflow_id).update(
                status=WarehouseMigration.Status.CRAWLING
            )

        self.start_crawl.side_effect = worker_starts_at_once
        response = self._create(json={"code": "Success", "data": {"account_id": "acct_example"}})

        assert response.status_code == 201, response.json()
        assert "fake-secret" not in response.content.decode()
        migration = WarehouseMigration.objects.for_team(self.team.pk).get()
        assert migration.credentials == {"api_key": "fake-key", "api_secret": "fake-secret"}
        # The API must not write `pending` back over a crawl that already started.
        assert migration.status == WarehouseMigration.Status.CRAWLING
        self.start_crawl.assert_called_once_with(
            team_id=self.team.pk, migration_id=migration.id, workflow_id=migration.workflow_id
        )

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
        page = self.client.get(f"{self.url}{migration.id}/items/").json()
        assert page["count"] == 4
        items = page["results"]
        assert len(items) == 4
        second = self.client.get(f"{self.url}{migration.id}/items/?limit=3&offset=3").json()
        assert [item["id"] for item in second["results"]] == [items[3]["id"]]
        (proposal,) = [item["proposal"] for item in items if item["proposal"]]
        assert proposal["inferred_tables"] == [{"vendor_table": "contact", "posthog_table": "contacts"}]
        assert proposal["unmatched_tables"] == ["email_event"]
        assert proposal["unused_posthog_tables"] == ["deals"]

    def test_items_list_survives_plans_stored_in_an_older_shape(self) -> None:
        migration = self._migration()
        # Saved before `alternative_names`, `vendor_table` and the table-match fields existed.
        old: dict[str, Any] = {
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
        by_name = {item["name"]: item for item in response.json()["results"]}
        assert by_name["old"]["proposal"]["schemas"][0]["alternative_names"] == []
        assert by_name["old"]["proposal"]["inferred_tables"] == []
        assert by_name["broken"]["proposal"] is None
        assert any("Refresh the migration" in caveat for caveat in by_name["broken"]["caveats"])

    @parameterized.expand(
        [
            ("own_item", "own", True, 200),
            ("other_migration", "other_migration", True, 404),
            ("other_team", "other_team", True, 404),
            ("flag_off", "own", False, 404),
        ]
    )
    def test_get_one_item(self, _name: str, owner: str, flag_on: bool, expected_status: int) -> None:
        migration = self._migration()
        item = self._item(migration, created_by=self.user)
        if owner == "other_migration":
            item = self._item(self._migration())
        elif owner == "other_team":
            other_team = self.create_team_with_organization(organization=self.organization)
            other = WarehouseMigration.objects.for_team(other_team.pk).create(
                team_id=other_team.pk, provider=WarehouseMigration.Provider.FIVETRAN
            )
            item = WarehouseMigrationItem.objects.for_team(other_team.pk).create(
                team_id=other_team.pk, migration=other, vendor_connection_id="conn_other", name="other"
            )
        self.flag.return_value = flag_on

        response = self.client.get(f"{self.url}{migration.id}/items/{item.id}/")

        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.json()["id"] == str(item.id)
            # The connect page shows who prepared the settings it prefills.
            assert response.json()["created_by"] == {"first_name": self.user.first_name, "email": self.user.email}

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
        # A mistyped kept id must not skip the connection it meant to keep.
        mistyped = {"keep_item_ids": [str(uuid4())]}
        assert self.client.post(url, mistyped, format="json").status_code == 400
        assert (
            not WarehouseMigrationItem.objects.for_team(self.team.pk)
            .filter(status=WarehouseMigrationItem.Status.SKIPPED)
            .exists()
        )

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

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.rate_limit.WarehouseMigrationCrawlThrottle.rate", new="1/hour")
    def test_session_callers_cannot_start_unlimited_crawls(self, _rate_limit_enabled: MagicMock) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        migration = self._migration()
        # A user without the flag is turned away before the throttle, so the team's budget is untouched.
        self.flag.return_value = False
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 404
        self.flag.return_value = True
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 200
        assert self._create(status_code=200, json={"code": "Success", "data": {}}).status_code == 429

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.rate_limit.WarehouseMigrationUploadStartThrottle.rate", new="1/hour")
    def test_session_callers_cannot_start_unlimited_uploads(self, _rate_limit_enabled: MagicMock) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        assert self.client.post(f"{self.url}upload/", {"provider": "fivetran"}).status_code == 201
        assert self.client.post(f"{self.url}upload/", {"provider": "fivetran"}).status_code == 429

    @parameterized.expand([("never_started", False, "failed"), ("started_but_unacknowledged", True, "crawling")])
    def test_a_crawl_that_cannot_start_fails_so_it_can_be_refreshed(
        self, _name: str, crawl_started: bool, expected_status: str
    ) -> None:
        migration = self._migration()

        def start(**kwargs: Any) -> None:
            if crawl_started:
                WarehouseMigration.objects.for_team(self.team.pk).filter(id=migration.id).update(
                    status=WarehouseMigration.Status.CRAWLING
                )
            raise RuntimeError("temporal is down")

        self.start_crawl.side_effect = start

        response = self.client.post(f"{self.url}{migration.id}/refresh/")

        assert response.status_code == 200, response.json()
        assert response.json()["status"] == expected_status
        if not crawl_started:
            self.start_crawl.side_effect = None
            assert self.client.post(f"{self.url}{migration.id}/refresh/").json()["status"] == "pending"

    def _upload(self, migration_id: Any, **body: Any) -> Any:
        return self.client.post(f"{self.url}{migration_id}/connections/", body, format="json")

    def test_upload_merges_batches_without_the_vendor_key_or_secrets(self) -> None:
        with patch(f"{_VIEW}.report_user_action") as report:
            started = self.client.post(f"{self.url}upload/", {"provider": "fivetran"})
        assert started.status_code == 201, started.json()
        assert started.json()["has_vendor_key"] is False
        assert report.call_args.args[2]["origin"] == "agent_upload"
        migration_id = started.json()["id"]

        first = self._upload(
            migration_id,
            account=_envelope({"account_id": "acct_example", "account_name": "Example Co"}),
            destinations=[
                _envelope(
                    {
                        "id": "grp_example",
                        "service": "snowflake",
                        "time_zone_offset": "-5",
                        "config": {"host": "example.snowflakecomputing.com", "password": "fake-unmasked-password"},
                    }
                )
            ],
            connections=[
                {"connection": _envelope(_fivetran_connection("conn_a")), "schema_config": None},
                {"connection": {"service": "hubspot"}},
                {"connection": _fivetran_connection("conn_bad", id=["conn_bad"])},
            ],
        )
        assert first.status_code == 400
        assert "Connection 1 (no id)" in first.json()["detail"]
        assert "Connection 2 (no valid id): the field `id` has the wrong type" in first.json()["detail"]

        # The destination came in an earlier batch, so its offset still moves 22:00 to UTC.
        schedule = {"schedule_type": "TIME_OF_DAY", "time_of_day": "22:00"}
        second = self._upload(
            migration_id, connections=[{"connection": _fivetran_connection("conn_b", schedule=schedule)}]
        )
        assert second.status_code == 200, second.json()
        assert [item["vendor_connection_id"] for item in second.json()["items"]] == ["conn_b"]

        items = WarehouseMigrationItem.objects.for_team(self.team.pk).filter(migration_id=migration_id)
        items.filter(vendor_connection_id="conn_a").update(status=WarehouseMigrationItem.Status.SKIPPED)
        third = self._upload(
            migration_id, connections=[{"connection": _fivetran_connection("conn_a", schema="renamed")}]
        )
        assert third.status_code == 200, third.json()

        migration = WarehouseMigration.objects.for_team(self.team.pk).get(id=migration_id)
        assert migration.account_name == "Example Co"
        assert dict(items.values_list("vendor_connection_id", "status")) == {"conn_a": "skipped", "conn_b": "pending"}
        assert items.get(vendor_connection_id="conn_a").name == "conn_a"
        assert migration.snapshot is not None
        snapshot_connections = {connection["id"]: connection for connection in migration.snapshot["connections"]}
        assert snapshot_connections["conn_b"]["schedule"]["time_of_day_utc"] == "03:00"
        stored = json.dumps([migration.snapshot, list(items.values())], default=str)
        assert "fake-unmasked" not in stored

        refresh = self.client.post(f"{self.url}{migration_id}/refresh/")
        assert refresh.status_code == 400
        assert "uploaded by an agent" in refresh.json()["detail"]

    @parameterized.expand(
        [
            ("too_many_connections", False, [{"connection": _fivetran_connection(f"conn_{i}")} for i in range(26)]),
            (
                "oversized_connection",
                False,
                [{"connection": _fivetran_connection("conn_big", config={"notes": "x" * 1_000_001})}],
            ),
            ("id_longer_than_its_column", False, [{"connection": _fivetran_connection("c" * 401)}]),
            ("migration_with_a_vendor_key", True, [{"connection": _fivetran_connection("conn_a")}]),
            ("migration_over_the_total_cap", False, [{"connection": _fivetran_connection("conn_a")}], 100),
            ("deeply_nested_config", False, [{"connection": _fivetran_connection("conn_deep", config=_nested(200))}]),
            ("nul_character", False, [{"connection": _fivetran_connection("conn_nul", config={"host": "db\x00"})}]),
            ("lone_surrogate", False, [{"connection": _fivetran_connection("conn_bad", config={"host": "db\ud800"})}]),
            ("nul_in_the_account", False, [], 10_000_000, {"account": {"account_name": "Example\x00"}}),
            (
                "interval_past_float_range",
                False,
                [{"connection": _fivetran_connection("conn_inf", schedule={"interval": _FLOAT_OVERFLOW})}],
            ),
        ]
    )
    def test_upload_refuses(
        self,
        _name: str,
        has_vendor_key: bool,
        connections: list[dict[str, Any]],
        max_snapshot_bytes: int = 10_000_000,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        migration = WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            provider=WarehouseMigration.Provider.FIVETRAN,
            status=WarehouseMigration.Status.READY,
            credentials={"api_key": "fake-key", "api_secret": "fake-secret"} if has_vendor_key else {},
        )

        # Sent as raw JSON, because the test client cannot encode `1e309`.
        body = json.dumps({"connections": connections, **(extra_body or {})}).replace(f'"{_FLOAT_OVERFLOW}"', "1e309")
        with patch(f"{_SNAPSHOT}.MAX_UPLOADED_SNAPSHOT_BYTES", max_snapshot_bytes):
            response = self.client.post(f"{self.url}{migration.id}/connections/", body, content_type="application/json")
        assert response.status_code == 400, response.content
        assert not WarehouseMigrationItem.objects.for_team(self.team.pk).exists()

    def test_another_teams_migration_or_a_malformed_id_is_not_found(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        migration = WarehouseMigration.objects.for_team(other_team.pk).create(
            team_id=other_team.pk, provider=WarehouseMigration.Provider.FIVETRAN
        )
        own = self._migration()
        assert self.client.get(f"{self.url}{migration.id}/").status_code == 404
        assert (
            self._upload(migration.id, connections=[{"connection": _fivetran_connection("conn_a")}]).status_code == 404
        )
        # Hex-only, so they pass a loose route pattern and would reach `UUID()`.
        assert self.client.get(f"{self.url}abc/").status_code == 404
        assert self.client.post(f"{self.url}{own.id}/items/abc/skip/").status_code == 404
        # Deleting removes the stored key, so it must never reach another team's migration.
        assert self.client.delete(f"{self.url}{migration.id}/").status_code == 404
        assert WarehouseMigration.objects.for_team(other_team.pk).filter(id=migration.id).exists()
        assert self.client.delete(f"{self.url}{own.id}/").status_code == 204
        assert not WarehouseMigration.objects.for_team(self.team.pk).filter(id=own.id).exists()


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
            # A retry under another prefix still finds the empty source instead of creating a second one.
            retry = self._apply(self._credential(), prefix="stripe_retry")
            assert retry.status_code == 400 and "Delete that source" in retry.json()["message"]
            assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 1

    def test_access_to_one_source_is_not_enough_to_apply(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@example.com", "testtest")
        membership = self.organization.memberships.get(user=member)
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="own", connection_id="own-conn", source_type=ExternalDataSourceType.STRIPE
        )
        AccessControl.objects.create(
            team=self.team, resource="external_data_source", resource_id=None, access_level="none"
        )
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=str(source.id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(member)

        assert self._apply(self._credential(user=member)).status_code == 403
        self.item.refresh_from_db()
        assert self.item.status == WarehouseMigrationItem.Status.PENDING
