import json
import datetime
from collections.abc import Sequence
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking import sweep
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.ranking.scorer import NO_VECTOR, ReportScoringOutcome, ScoringError
from products.signals.backend.ranking.serving_manifest import SERVED_ROLE
from products.signals.backend.ranking.sweep import (
    SKIPPED_DISABLED,
    SKIPPED_NO_MANIFEST,
    ScoringCandidate,
    reports_due_for_scoring,
    score_inbox_reports,
)
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE, EMBEDDING_RENDERING_TITLE_SUMMARY

MANIFEST = "2026-09-01T00:00:00+00:00"
OTHER_MANIFEST = "2026-08-31T00:00:00+00:00"
MODEL_KEY = "report_embeddings@2026-09-01"


def _ranking_score(*, embedding_inserted_at: datetime.datetime, manifest_version: str, scored_at: datetime.datetime):
    return RankingScore(
        scored_at=scored_at,
        embedding_inserted_at=embedding_inserted_at,
        manifest_version=manifest_version,
        served_key=MODEL_KEY,
        results={
            MODEL_KEY: RankingModelResult(
                model_name="report_embeddings",
                model_version="2026-09-01",
                model_kind="xgboost",
                roles=[SERVED_ROLE],
                feature_schema_version=1,
                status="scored",
                scores={"open": 0.5},
            )
        },
    )


@override_settings(INBOX_RANKING_SCORING_MAX_AGE_DAYS=30)
class TestReportsDueForScoring(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {REPORT_EMBEDDINGS_TABLE}", flush=False, team_id=self.team.pk)
        self.landed = (timezone.now() - datetime.timedelta(hours=6)).replace(microsecond=0)

    def _report(
        self, *, status: str = SignalReport.Status.READY, age_days: int = 1, team: Team | None = None
    ) -> SignalReport:
        report = SignalReport.objects.create(team=team or self.team, status=status, title="A")
        SignalReport.objects.filter(id=report.id).update(created_at=timezone.now() - datetime.timedelta(days=age_days))
        report.refresh_from_db()
        return report

    def _vector(
        self,
        report: SignalReport,
        *,
        hours: int = 0,
        deleted: bool = False,
        rendering: str = EMBEDDING_RENDERING_TITLE_SUMMARY,
        team_id: int | None = None,
    ) -> datetime.datetime:
        at = self.landed + datetime.timedelta(hours=hours)
        sync_execute(
            f"""
            INSERT INTO {REPORT_EMBEDDINGS_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id or report.team_id,
                    "signals",
                    "report",
                    rendering,
                    str(report.id),
                    report.created_at,
                    at,
                    "a report",
                    json.dumps({"deleted": deleted}),
                    [0.0] * EMBEDDING_DIMENSIONS,
                    at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id or report.team_id,
        )
        return at

    def _score(
        self,
        report: SignalReport,
        *,
        embedding_inserted_at: datetime.datetime,
        manifest_version: str = MANIFEST,
        scored_at: datetime.datetime | None = None,
    ) -> None:
        score = _ranking_score(
            embedding_inserted_at=embedding_inserted_at,
            manifest_version=manifest_version,
            scored_at=scored_at or timezone.now(),
        )
        SignalReportArtefact.objects.create(
            team=report.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            content=score.model_dump_json(),
        )

    def _due(self, limit: int = 100) -> list[ScoringCandidate]:
        return reports_due_for_scoring(
            timezone.now(), manifest_version=MANIFEST, rendering=EMBEDDING_RENDERING_TITLE_SUMMARY, limit=limit
        )

    def test_a_live_vector_with_no_score_is_due(self) -> None:
        report = self._report()
        landed = self._vector(report)

        assert self._due() == [
            ScoringCandidate(team_id=self.team.pk, report_id=str(report.id), vector_inserted_at=landed)
        ]

    def test_a_score_of_the_newest_vector_under_the_current_manifest_is_not_due(self) -> None:
        report = self._report()
        self._score(report, embedding_inserted_at=self._vector(report))

        assert self._due() == []

    def test_a_newer_vector_after_a_text_edit_is_due_though_updated_at_did_not_move(self) -> None:
        report = self._report()
        self._score(report, embedding_inserted_at=self._vector(report))
        updated_at = report.updated_at
        report.title, report.summary = "B", "An edited summary"
        report.save(update_fields=["title", "summary"])
        newer = self._vector(report, hours=1)

        report.refresh_from_db()
        assert report.updated_at == updated_at
        assert [candidate.vector_inserted_at for candidate in self._due()] == [newer]

    def test_a_score_under_another_manifest_is_due(self) -> None:
        report = self._report()
        self._score(report, embedding_inserted_at=self._vector(report), manifest_version=OTHER_MANIFEST)

        assert [candidate.report_id for candidate in self._due()] == [str(report.id)]

    @parameterized.expand(
        [
            ("newest_row_is_a_tombstone", {}, {"tombstone": True}),
            ("resolved", {"status": SignalReport.Status.RESOLVED}, {}),
            ("suppressed", {"status": SignalReport.Status.SUPPRESSED}, {}),
            ("potential", {"status": SignalReport.Status.POTENTIAL}, {}),
            ("older_than_the_max_age", {"age_days": 31}, {}),
            ("no_vector", {}, {"no_vector": True}),
            ("vector_of_another_rendering", {}, {"rendering": EMBEDDING_RENDERING_TITLE}),
            ("vector_under_another_team", {}, {"other_team": True}),
        ]
    )
    def test_never_due(self, _name: str, report_kwargs: dict[str, Any], vector: dict[str, Any]) -> None:
        report = self._report(**report_kwargs)
        if not vector.get("no_vector"):
            self._vector(
                report,
                rendering=vector.get("rendering", EMBEDDING_RENDERING_TITLE_SUMMARY),
                team_id=self.team.pk + 1 if vector.get("other_team") else None,
            )
        if vector.get("tombstone"):
            self._vector(report, hours=1, deleted=True)

        assert self._due() == []

    def test_the_cap_keeps_unscored_reports_first_then_the_oldest_score(self) -> None:
        now = timezone.now()
        stale_recent, stale_old = self._report(), self._report()
        self._score(
            stale_recent,
            embedding_inserted_at=self._vector(stale_recent),
            manifest_version=OTHER_MANIFEST,
            scored_at=now - datetime.timedelta(hours=1),
        )
        self._score(
            stale_old,
            embedding_inserted_at=self._vector(stale_old),
            manifest_version=OTHER_MANIFEST,
            scored_at=now - datetime.timedelta(hours=2),
        )
        unscored = self._report()
        self._vector(unscored)

        assert [candidate.report_id for candidate in self._due(limit=2)] == [str(unscored.id), str(stale_old.id)]


def _outcomes(report_ids: Sequence[str]) -> list[ReportScoringOutcome]:
    return [
        ReportScoringOutcome(report_id=report_id, score=None, reason=NO_VECTOR)
        if report_id.startswith("missing")
        else ReportScoringOutcome(
            report_id=report_id,
            score=_ranking_score(
                embedding_inserted_at=timezone.now(), manifest_version=MANIFEST, scored_at=timezone.now()
            ),
            reason=None,
        )
        for report_id in report_ids
    ]


@override_settings(INBOX_RANKING_SCORING_ENABLED=True, INBOX_RANKING_SCORING_MAX_REPORTS_PER_TICK=100)
class TestScoreInboxReports(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        serving = MagicMock()
        serving.manifest.manifest_version = MANIFEST
        self.load_serving_set = self._patch("load_serving_set", return_value=serving)
        self._patch("served_rendering", return_value=EMBEDDING_RENDERING_TITLE_SUMMARY)
        self.due = self._patch(
            "reports_due_for_scoring",
            return_value=[
                ScoringCandidate(team_id=1, report_id="a", vector_inserted_at=timezone.now()),
                ScoringCandidate(team_id=2, report_id="b", vector_inserted_at=timezone.now()),
                ScoringCandidate(team_id=1, report_id="missing", vector_inserted_at=timezone.now()),
            ],
        )
        self.score_reports = self._patch("score_reports", side_effect=lambda team_id, ids, **_: _outcomes(ids))

    def _patch(self, name: str, **kwargs: Any) -> MagicMock:
        patcher = patch.object(sweep, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def test_disabled_reads_and_writes_nothing(self) -> None:
        with override_settings(INBOX_RANKING_SCORING_ENABLED=False):
            result = score_inbox_reports()

        assert result.skipped_reason == SKIPPED_DISABLED
        self.load_serving_set.assert_not_called()
        self.due.assert_not_called()
        self.score_reports.assert_not_called()

    def test_no_manifest_scores_nothing(self) -> None:
        self.load_serving_set.return_value = None

        result = score_inbox_reports()

        assert result.skipped_reason == SKIPPED_NO_MANIFEST
        self.due.assert_not_called()
        self.score_reports.assert_not_called()

    def test_one_persisting_call_per_team_with_that_teams_ids_only(self) -> None:
        result = score_inbox_reports()

        assert sorted(
            (call.args[0], call.args[1], call.kwargs["persist"]) for call in self.score_reports.mock_calls
        ) == [
            (1, ["a", "missing"], True),
            (2, ["b"], True),
        ]
        assert (result.candidates, result.scored, result.no_vector, result.teams, result.failed_teams) == (
            3,
            2,
            1,
            2,
            0,
        )
        assert result.manifest_version == MANIFEST

    def test_one_team_failing_is_counted_and_the_next_team_is_still_scored(self) -> None:
        def score(team_id: int, ids: Sequence[str], **_: Any) -> list[ReportScoringOutcome]:
            if team_id == 1:
                raise RuntimeError("ClickHouse went away")
            return _outcomes(ids)

        self.score_reports.side_effect = score

        result = score_inbox_reports()

        assert (result.scored, result.failed_teams) == (1, 1)

    def test_a_scoring_error_aborts_the_run(self) -> None:
        self.score_reports.side_effect = ScoringError("served model is not served")

        with self.assertRaises(ScoringError):
            score_inbox_reports()

        assert self.score_reports.call_count == 1
