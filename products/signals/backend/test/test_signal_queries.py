from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.signals.backend.temporal.signal_queries import (
    EMBEDDING_MODEL,
    ReportSignalMeta,
    fetch_signals_for_report_sync,
    fetch_source_products_for_reports,
)

_MODEL_TABLE = f"distributed_posthog_document_embeddings_{EMBEDDING_MODEL.value.replace('-', '_')}"
_EMBEDDING = [0.0] * 1536


class _SignalEmbeddingsTestBase(ClickhouseTestMixin, APIBaseTest):
    def _emit_version(
        self,
        *,
        document_id: str,
        report_id: str,
        source_product: str,
        inserted_at: datetime,
        deleted: bool = False,
        content: str = "the signal content",
        skill_name: str | None = None,
    ) -> None:
        """Write one version of a signal document straight to the model-specific embeddings table.

        Multiple versions of the same document_id (varying inserted_at) model the
        ReplacingMergeTree's pre-merge state that the argMax dedup has to resolve.
        """
        metadata: dict = {
            "report_id": report_id,
            "source_product": source_product,
            "source_type": "some_type",
            "source_id": f"src-{document_id}",
            "deleted": deleted,
        }
        if skill_name is not None:
            metadata["extra"] = {"skill_name": skill_name}
        sync_execute(
            f"""
            INSERT INTO {_MODEL_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    self.team.pk,
                    "signals",
                    "signal",
                    "plain",
                    document_id,
                    inserted_at,
                    inserted_at,
                    content,
                    json.dumps(metadata),
                    _EMBEDDING,
                    inserted_at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=self.team.pk,
        )

    def setUp(self) -> None:
        super().setUp()
        # Anchor to "now" so rows stay inside the table's 3-month TTL window; assertions depend
        # only on the relative inserted_at ordering between versions, not the absolute timestamp.
        self.base = datetime.now(UTC) - timedelta(days=2)
        sync_execute(f"TRUNCATE TABLE {_MODEL_TABLE}", flush=False, team_id=self.team.pk)


class TestFetchSourceProductsForReports(_SignalEmbeddingsTestBase):
    def test_empty_report_ids_returns_empty_without_querying(self) -> None:
        # Guards the early return: an empty list would otherwise compile to `report_id IN ()` and raise.
        assert fetch_source_products_for_reports(self.team, []) == {}

    def test_maps_each_report_to_its_sorted_distinct_source_products(self) -> None:
        self._emit_version(document_id="d1", report_id="rA", source_product="errors", inserted_at=self.base)
        self._emit_version(document_id="d2", report_id="rA", source_product="replay", inserted_at=self.base)
        # duplicate source_product within a report collapses to one entry
        self._emit_version(document_id="d3", report_id="rA", source_product="errors", inserted_at=self.base)
        self._emit_version(document_id="d4", report_id="rB", source_product="surveys", inserted_at=self.base)

        result = fetch_source_products_for_reports(self.team, ["rA", "rB"])

        assert result == {
            "rA": ReportSignalMeta(source_products=["errors", "replay"], scout_name=None),
            "rB": ReportSignalMeta(source_products=["surveys"], scout_name=None),
        }

    def test_only_returns_requested_reports(self) -> None:
        self._emit_version(document_id="d1", report_id="wanted", source_product="errors", inserted_at=self.base)
        self._emit_version(document_id="d2", report_id="unwanted", source_product="replay", inserted_at=self.base)

        result = fetch_source_products_for_reports(self.team, ["wanted"])

        assert result == {"wanted": ReportSignalMeta(source_products=["errors"], scout_name=None)}

    def test_extracts_authoring_scout_name_from_signal_extra(self) -> None:
        # Guards the nested `extra.skill_name` extraction that drives the inbox's "Scout · <name>"
        # label — a broken JSON path or the anyIf filter would silently drop it back to null.
        self._emit_version(
            document_id="d1",
            report_id="rScout",
            source_product="signals_scout",
            inserted_at=self.base,
            skill_name="signals-scout-error-tracking",
        )
        self._emit_version(document_id="d2", report_id="rPipeline", source_product="errors", inserted_at=self.base)

        result = fetch_source_products_for_reports(self.team, ["rScout", "rPipeline"])

        assert result == {
            "rScout": ReportSignalMeta(source_products=["signals_scout"], scout_name="signals-scout-error-tracking"),
            "rPipeline": ReportSignalMeta(source_products=["errors"], scout_name=None),
        }

    @parameterized.expand(
        [
            # A signal re-grouped to a different report must count under its latest report only —
            # never the old one. Pushing the report_id filter before the argMax would resurface it
            # under rOld; keeping it after preserves "latest version wins".
            (
                "regrouped_to_new_report",
                ("rOld", False),
                ("rNew", False),
                ["rOld", "rNew"],
                {"rNew": ReportSignalMeta(source_products=["errors"], scout_name=None)},
            ),
            # Soft-delete re-emits the signal with deleted=True and a newer inserted_at -> it drops out.
            ("deleted_in_latest_version", ("rA", False), ("rA", True), ["rA"], {}),
            # ...and a delete that was later undone (newer non-deleted version) comes back.
            (
                "revived_in_latest_version",
                ("rA", True),
                ("rA", False),
                ["rA"],
                {"rA": ReportSignalMeta(source_products=["errors"], scout_name=None)},
            ),
        ]
    )
    def test_latest_version_wins(
        self,
        _name: str,
        first: tuple[str, bool],
        latest: tuple[str, bool],
        report_ids: list[str],
        expected: dict[str, ReportSignalMeta],
    ) -> None:
        first_report, first_deleted = first
        latest_report, latest_deleted = latest
        self._emit_version(
            document_id="moving",
            report_id=first_report,
            source_product="errors",
            inserted_at=self.base,
            deleted=first_deleted,
        )
        self._emit_version(
            document_id="moving",
            report_id=latest_report,
            source_product="errors",
            inserted_at=self.base + timedelta(hours=1),
            deleted=latest_deleted,
        )

        assert fetch_source_products_for_reports(self.team, report_ids) == expected


class TestFetchSignalsForReportSync(_SignalEmbeddingsTestBase):
    def _signal_ids(self, report_id: str) -> set[str]:
        return {s["signal_id"] for s in fetch_signals_for_report_sync(self.team, report_id)}

    def test_returns_only_the_reports_non_deleted_signals(self) -> None:
        self._emit_version(document_id="a", report_id="rA", source_product="errors", inserted_at=self.base)
        self._emit_version(document_id="b", report_id="rA", source_product="replay", inserted_at=self.base)
        self._emit_version(document_id="c", report_id="rB", source_product="surveys", inserted_at=self.base)

        assert self._signal_ids("rA") == {"a", "b"}

    @parameterized.expand(
        [
            # A re-grouped signal belongs to its latest report only — the candidate prefilter finds it
            # (it once carried rOld) but the outer report filter keeps it under rNew, never rOld.
            ("regrouped_to_new_report", ("rOld", False), ("rNew", False), "rOld", set()),
            ("regrouped_visible_under_new", ("rOld", False), ("rNew", False), "rNew", {"moving"}),
            # The latest version's deleted flag wins.
            ("deleted_in_latest_version", ("rA", False), ("rA", True), "rA", set()),
            ("revived_in_latest_version", ("rA", True), ("rA", False), "rA", {"moving"}),
        ]
    )
    def test_latest_version_wins(
        self,
        _name: str,
        first: tuple[str, bool],
        latest: tuple[str, bool],
        query_report: str,
        expected_ids: set[str],
    ) -> None:
        first_report, first_deleted = first
        latest_report, latest_deleted = latest
        self._emit_version(
            document_id="moving",
            report_id=first_report,
            source_product="errors",
            inserted_at=self.base,
            deleted=first_deleted,
        )
        self._emit_version(
            document_id="moving",
            report_id=latest_report,
            source_product="errors",
            inserted_at=self.base + timedelta(hours=1),
            deleted=latest_deleted,
        )

        assert self._signal_ids(query_report) == expected_ids

    def test_returns_latest_content_for_a_revised_signal(self) -> None:
        # The dedup must surface the newest version's content, not an arbitrary one.
        self._emit_version(
            document_id="x", report_id="rA", source_product="errors", inserted_at=self.base, content="old text"
        )
        self._emit_version(
            document_id="x",
            report_id="rA",
            source_product="errors",
            inserted_at=self.base + timedelta(hours=1),
            content="new text",
        )

        signals = fetch_signals_for_report_sync(self.team, "rA")

        assert [s["content"] for s in signals] == ["new text"]
