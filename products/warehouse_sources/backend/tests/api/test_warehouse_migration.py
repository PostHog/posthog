from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

import requests
import requests_mock
from parameterized import parameterized

from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedSchema, TablePair
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.types import ExternalDataSourceType

_FACADE = "products.warehouse_sources.backend.facade.warehouse_migration"
_SERVICE = "products.warehouse_sources.backend.migration.service"


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
        # Deleting removes the stored key, so it must never reach another team's migration.
        assert self.client.delete(f"{self.url}{migration.id}/").status_code == 404
        assert WarehouseMigration.objects.for_team(other_team.pk).filter(id=migration.id).exists()
        assert self.client.delete(f"{self.url}{own.id}/").status_code == 204
        assert not WarehouseMigration.objects.for_team(self.team.pk).filter(id=own.id).exists()
