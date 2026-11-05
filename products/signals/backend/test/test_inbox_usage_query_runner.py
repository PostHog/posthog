import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.signal_metadata import EMBEDDING_MODEL


class TestInboxUsageQueryRunner(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.base = datetime.now(UTC) - timedelta(days=2)

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
