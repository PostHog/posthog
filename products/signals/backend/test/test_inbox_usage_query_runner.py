import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import QueryStatus

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, Team
from posthog.models.scoping import team_scope
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.signal_metadata import EMBEDDING_MODEL
from products.signals.backend.test.test_scout_harness_api import _make_run


class TestInboxUsageQueryRunner(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.pk))
        self.base = datetime.now(UTC) - timedelta(days=2)

    @parameterized.expand([("summary",), ("sql",), ("saved_view",)])
    def test_usage_access_is_checked_on_cached_and_async_reads(self, query_kind: str) -> None:
        run = _make_run(self.team)
        SignalSpend.objects.for_team(self.team.pk).create(
            team=self.team,
            kind=SignalSpend.Kind.SCOUT_RUN,
            scout_run=run,
            task_run_id=run.task_run_id,
            spend="7.25",
            finalized_at=timezone.now() - timedelta(minutes=1),
        )
        query = {"kind": "InboxUsageQuery", "dateRange": {"date_from": "-7d"}}
        if query_kind != "summary":
            query = {"kind": "HogQLQuery", "query": "SELECT credits FROM system.signal_spend"}
            if query_kind == "saved_view":
                DataWarehouseSavedQuery.objects.create(team=self.team, name="usage_receipts", query=query)
                query = {"kind": "HogQLQuery", "query": "SELECT credits FROM usage_receipts"}
        path = f"/api/projects/{self.team.pk}/query/"

        def execute_without_initial_labels(task_signature, manager, query_status):
            query_status.labels = None
            manager.store_query_status(query_status)
            task_signature()

        with patch(
            "posthog.clickhouse.client.execute_async.add_task_to_on_commit",
            side_effect=execute_without_initial_labels,
        ):
            queued = self.client.post(path, {"query": query, "refresh": "async"}, format="json")
        assert queued.status_code in (200, 202), queued.content
        query_id = queued.json()["query_status"]["id"]
        result_path = f"{path}{query_id}/"
        result = self.client.get(result_path)
        assert result.status_code == 200, result.content
        assert "required_scope:signal_usage:read" in result.json()["query_status"]["labels"]

        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        share = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        public_query_id = uuid.uuid4().hex
        QueryStatusManager(public_query_id, self.team.pk).store_query_status(
            QueryStatus(id=public_query_id, team_id=self.team.pk, complete=True, results={"results": [[1]]})
        )
        self.client.logout()
        assert self.client.get(f"{path}{public_query_id}/?sharing_access_token={share.access_token}").status_code == 200
        assert self.client.get(f"{result_path}?sharing_access_token={share.access_token}").status_code == 403
        self.client.force_login(self.user)

        for scopes, expected in [(["query:read", "signal_usage:read"], 200), (["query:read"], 403)]:
            raw = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="usage reader",
                user=self.user,
                secure_value=hash_key_value(raw),
                scopes=scopes,
                scoped_teams=[self.team.pk],
            )
            self.client.logout()
            cached = self.client.post(path, {"query": query}, format="json", HTTP_AUTHORIZATION=f"Bearer {raw}")
            stored = self.client.get(result_path, HTTP_AUTHORIZATION=f"Bearer {raw}")
            assert cached.status_code == stored.status_code == expected, (cached.content, stored.content)
            if expected == 200:
                assert cached.json()["is_cached"] is True

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource="signal_usage",
            access_level="none",
            organization_member=self.organization_membership,
        )
        self.client.force_login(self.user)
        assert self.client.get(result_path).status_code == 403
        assert self.client.post(path, {"query": query}, format="json").status_code == 403

    def test_retained_scout_receipts_reconcile_and_unknown_visibility_is_incomplete(self) -> None:
        for metadata, amount in [({}, "7.25"), ({"scout_trial": {"version": 1}}, "99")]:
            run = _make_run(self.team, metadata=metadata)
            receipt = SignalSpend.objects.for_team(self.team.pk).create(
                team=self.team,
                kind=SignalSpend.Kind.SCOUT_RUN,
                scout_run=run,
                task_run_id=run.task_run_id,
                spend=amount,
                finalized_at=timezone.now() - timedelta(minutes=1),
            )
            type(run.task_run).objects.filter(team_id=self.team.pk, id=run.task_run_id).delete()
            receipt.refresh_from_db()
            assert receipt.is_private is bool(metadata)
        SignalSpend.objects.for_team(self.team.pk).create(
            team=self.team,
            kind=SignalSpend.Kind.SCOUT_RUN,
            scout_run_id=uuid.uuid4(),
            task_run_id=uuid.uuid4(),
            spend="123",
            finalized_at=timezone.now() - timedelta(minutes=1),
        )
        summary = self.client.get(f"/api/projects/{self.team.pk}/signals/usage/")
        assert summary.status_code == 200, summary.content
        assert Decimal(summary.json()["total_credits"]) == Decimal("7.25")
        assert summary.json()["incomplete"] is True
        sql = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": {"kind": "HogQLQuery", "query": "SELECT sum(credits) FROM system.signal_spend"}},
            format="json",
        )
        assert sql.status_code == 200, sql.content
        assert Decimal(str(sql.json()["results"][0][0])) == Decimal("7.25")

    def _emit_version(
        self,
        *,
        document_id: str,
        report_id: str,
        source_product: str,
        inserted_at: datetime,
        spend_metadata: dict | None = None,
    ) -> None:
        sync_execute(
            f"""INSERT INTO distributed_posthog_document_embeddings_{EMBEDDING_MODEL.value.replace("-", "_")}
                (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, metadata, embedding, _timestamp, _offset, _partition)
                VALUES""",
            [
                (
                    self.team.id,
                    "signals",
                    "signal",
                    "plain",
                    document_id,
                    inserted_at,
                    inserted_at,
                    "",
                    json.dumps(
                        {
                            "report_id": report_id,
                            "source_product": source_product,
                            "source_type": "some_type",
                            **(spend_metadata or {}),
                        }
                    ),
                    [0.0] * 1536,
                    inserted_at,
                    0,
                    0,
                )
            ],
            team_id=self.team.id,
        )

    def test_monthly_usage_attributes_implementation_once_and_preserves_unknown_sources(self) -> None:
        signal_id = uuid.uuid4()
        research_signal_id = uuid.uuid4()
        report = SignalReport.objects.create(
            team=self.team, triggering_signal_id=signal_id, status=SignalReport.Status.DELETED
        )
        settled_at = datetime(self.base.year, self.base.month, 1, tzinfo=UTC)
        self._emit_version(
            document_id=str(signal_id),
            report_id=str(report.id),
            source_product="linear",
            inserted_at=self.base,
            spend_metadata={"total_spend": 999},
        )
        self._emit_version(
            document_id=str(signal_id),
            report_id=str(report.id),
            source_product="github",
            inserted_at=self.base + timedelta(hours=1),
            spend_metadata={"total_spend": 999},
        )
        self._emit_version(
            document_id=str(research_signal_id),
            report_id=str(report.id),
            source_product="linear",
            inserted_at=self.base,
        )
        receipts = [
            SignalSpend(team=self.team, kind=SignalSpend.Kind.AD_HOC, signal_id=signal_id, spend="2.1250"),
            SignalSpend(
                team=self.team,
                kind=SignalSpend.Kind.RESEARCH,
                signal_id=research_signal_id,
                task_run_id=uuid.uuid4(),
                spend="3",
            ),
            SignalSpend(
                team=self.team,
                kind=SignalSpend.Kind.REVIEWER_TRIGGERED_IMPLEMENTATION,
                report=report,
                task_run_id=uuid.uuid4(),
                spend="5",
                billing_exempt=True,
            ),
            SignalSpend(
                team=self.team,
                kind=SignalSpend.Kind.SCOUT_TRIGGERED_IMPLEMENTATION,
                report=report,
                task_run_id=uuid.uuid4(),
                spend="7",
            ),
            SignalSpend(
                team=self.team, kind=SignalSpend.Kind.AD_HOC, signal_id=uuid.uuid4(), spend="11", accounting_failed=True
            ),
        ]
        receipts.extend(
            SignalSpend(team=self.team, kind=SignalSpend.Kind.AD_HOC, signal_id=uuid.uuid4(), spend="0.0001")
            for _ in range(1001)
        )
        for receipt in receipts:
            receipt.finalized_at = settled_at
        SignalSpend.objects.for_team(self.team.id).bulk_create(receipts)
        SignalSpend.objects.for_team(self.team.id).filter(id__in=[receipt.id for receipt in receipts]).update(
            created_at=settled_at - timedelta(days=40)
        )
        SignalSpend.objects.for_team(self.team.id).create(
            team=self.team,
            kind=SignalSpend.Kind.AD_HOC,
            signal_id=uuid.uuid4(),
            spend=999,
            finalized_at=settled_at - timedelta(microseconds=1),
        )
        other_team = Team.objects.create(organization=self.organization)
        SignalSpend.objects.for_team(other_team.id).create(
            team=other_team, kind=SignalSpend.Kind.AD_HOC, signal_id=signal_id, spend=999, finalized_at=settled_at
        )
        with self.capture_select_queries() as queries:
            response = self.client.get(f"/api/projects/{self.team.id}/signals/usage/?month={self.base:%Y-%m}")
        assert len(queries) == 1

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["total_credits"] == "28.2251"
        assert data["exempt_credits"] == "5.0000"
        assert data["incomplete"] is True
        assert data["attribution_incomplete"] is True
        assert data["sources"] == [
            {
                "source_product": "github",
                "source_type": "some_type",
                "processing_credits": "2.1250",
                "research_credits": "0.0000",
                "implementation_credits": "12.0000",
                "total_credits": "14.1250",
                "exempt_credits": "5.0000",
                "incomplete": False,
            },
            {
                "source_product": None,
                "source_type": None,
                "processing_credits": "11.1001",
                "research_credits": "0.0000",
                "implementation_credits": "0.0000",
                "total_credits": "11.1001",
                "exempt_credits": "0.0000",
                "incomplete": True,
            },
            {
                "source_product": "linear",
                "source_type": "some_type",
                "processing_credits": "0.0000",
                "research_credits": "3.0000",
                "implementation_credits": "0.0000",
                "total_credits": "3.0000",
                "exempt_credits": "0.0000",
                "incomplete": False,
            },
        ]
