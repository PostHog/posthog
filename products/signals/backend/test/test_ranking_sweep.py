import json
import datetime
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking import scorer, sweep
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.ranking.model_store import ModelLoadError
from products.signals.backend.ranking.scorer import NO_VECTOR, ReportScoringOutcome, ScoringError
from products.signals.backend.ranking.sweep import ScoringCandidate, reports_due_for_scoring, score_inbox_reports
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE_SUMMARY

MANIFEST = "manifest-b"
OLD_MANIFEST = "manifest-a"


def _score(*, embedding_inserted_at: datetime.datetime, manifest_version: str, scored_at: datetime.datetime) -> str:
    served = RankingModelResult(
        model_name="report_embeddings",
        model_version="2026-09-01",
        model_kind="xgboost",
        roles=["served"],
        feature_schema_version=1,
        status="scored",
        scores={"open": 0.5},
    )
    return RankingScore(
        scored_at=scored_at,
        embedding_inserted_at=embedding_inserted_at,
        manifest_version=manifest_version,
        served_key=served.key,
        results={served.key: served},
    ).model_dump_json()


class TestReportsDueForScoring(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {REPORT_EMBEDDINGS_TABLE}", flush=False, team_id=self.team.pk)
        # Whole seconds: the vector table keeps inserted_at at millisecond precision.
        self.now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)

    def _report(self, *, status: str = SignalReport.Status.READY, age_days: int = 2, team: Team | None = None) -> str:
        report = SignalReport.objects.create(team=team or self.team, status=status, title="t", summary="s")
        SignalReport.objects.filter(id=report.id).update(created_at=self.now - datetime.timedelta(days=age_days))
        return str(report.id)

    def _vector(
        self, report_id: str, *, hours_ago: int, deleted: bool = False, team_id: int | None = None
    ) -> datetime.datetime:
        report = SignalReport.objects.get(id=report_id)
        inserted_at = self.now - datetime.timedelta(hours=hours_ago)
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
                    EMBEDDING_RENDERING_TITLE_SUMMARY,
                    report_id,
                    report.created_at.replace(tzinfo=None),
                    inserted_at.replace(tzinfo=None),
                    "a report",
                    json.dumps({"deleted": deleted}),
                    [0.0] * EMBEDDING_DIMENSIONS,
                    inserted_at.replace(tzinfo=None),
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=self.team.pk,
        )
        return inserted_at

    def _scored(
        self, report_id: str, *, vector_at: datetime.datetime, manifest: str = MANIFEST, hours_ago: int = 1
    ) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            content=_score(
                embedding_inserted_at=vector_at,
                manifest_version=manifest,
                scored_at=self.now - datetime.timedelta(hours=hours_ago),
            ),
        )

    def _due(self, limit: int = 100) -> list[str]:
        candidates = reports_due_for_scoring(
            self.now, manifest_version=MANIFEST, rendering=EMBEDDING_RENDERING_TITLE_SUMMARY, limit=limit
        )
        return [candidate.report_id for candidate in candidates]

    def test_due_reports_are_the_in_window_scorable_ones_whose_score_is_missing_or_stale(self) -> None:
        unscored = self._report()
        self._vector(unscored, hours_ago=5)

        current = self._report()
        self._scored(current, vector_at=self._vector(current, hours_ago=5))

        edited = self._report()
        self._scored(edited, vector_at=self._vector(edited, hours_ago=5))
        edited_report = SignalReport.objects.get(id=edited)
        updated_at = edited_report.updated_at
        edited_report.title, edited_report.summary = "new title", "new summary"
        edited_report.save(update_fields=["title", "summary"])
        self._vector(edited, hours_ago=2)
        assert SignalReport.objects.get(id=edited).updated_at == updated_at

        other_manifest = self._report()
        self._scored(other_manifest, vector_at=self._vector(other_manifest, hours_ago=5), manifest=OLD_MANIFEST)

        retracted = self._report()
        self._vector(retracted, hours_ago=5)
        self._vector(retracted, hours_ago=2, deleted=True)
        resolved = self._report(status=SignalReport.Status.RESOLVED)
        self._vector(resolved, hours_ago=5)
        suppressed = self._report(status=SignalReport.Status.SUPPRESSED)
        self._vector(suppressed, hours_ago=5)
        too_old = self._report(age_days=40)
        self._vector(too_old, hours_ago=5)
        self._report()
        other_team = Team.objects.create(organization=self.organization)
        wrong_team = self._report(team=other_team)
        self._vector(wrong_team, hours_ago=5, team_id=self.team.pk)

        assert sorted(self._due()) == sorted([unscored, edited, other_manifest])

    def test_the_cap_keeps_unscored_reports_first_then_the_oldest_scores(self) -> None:
        recently_scored, long_ago_scored, unscored = self._report(), self._report(), self._report()
        self._scored(recently_scored, vector_at=self._vector(recently_scored, hours_ago=5), manifest=OLD_MANIFEST)
        self._scored(
            long_ago_scored, vector_at=self._vector(long_ago_scored, hours_ago=5), manifest=OLD_MANIFEST, hours_ago=3
        )
        self._vector(unscored, hours_ago=5)

        assert self._due(limit=2) == [unscored, long_ago_scored]


class TestScoreInboxReports(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.serving = SimpleNamespace(manifest=SimpleNamespace(manifest_version=MANIFEST))
        self.load_serving_set = self._patch(sweep, "load_serving_set", return_value=self.serving)
        self._patch(scorer, "served_rendering", return_value=EMBEDDING_RENDERING_TITLE_SUMMARY)
        self.due = self._patch(sweep, "reports_due_for_scoring", return_value=[])
        self.score_reports = self._patch(scorer, "score_reports", side_effect=self._outcomes)
        self.capture = MagicMock()
        self.capture_scopes = 0
        self._patch(sweep, "ph_scoped_capture", new=self._capture_scope)
        self.failing_teams: dict[int, Exception] = {}
        settings_override = override_settings(INBOX_RANKING_SCORING_ENABLED=True)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def _patch(self, target: Any, name: str, **kwargs: Any) -> MagicMock:
        patcher = patch.object(target, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @contextmanager
    def _capture_scope(self) -> Iterator[MagicMock]:
        self.capture_scopes += 1
        yield self.capture

    def _outcomes(
        self,
        team_id: int,
        report_ids: list[str],
        *,
        persist: bool,
        now: datetime.datetime,
        serving: Any = None,
        capture: Any = None,
    ) -> list:
        if team_id in self.failing_teams:
            raise self.failing_teams[team_id]
        return [
            ReportScoringOutcome(report_id=report_id, score=None, reason=NO_VECTOR)
            if report_id.startswith("novec")
            else ReportScoringOutcome(report_id=report_id, score=MagicMock(), reason=None)
            for report_id in report_ids
        ]

    def _candidates(self, *pairs: tuple[int, str]) -> None:
        at = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
        self.due.return_value = [
            ScoringCandidate(team_id=team_id, report_id=report_id, vector_inserted_at=at)
            for team_id, report_id in pairs
        ]

    def test_disabled_reads_and_writes_nothing(self) -> None:
        with override_settings(INBOX_RANKING_SCORING_ENABLED=False):
            result = score_inbox_reports()

        assert result.skipped_reason == "disabled"
        self.load_serving_set.assert_not_called()
        self.due.assert_not_called()
        self.score_reports.assert_not_called()

    def test_no_manifest_scores_nothing(self) -> None:
        self.load_serving_set.return_value = None

        result = score_inbox_reports()

        assert result.skipped_reason == "no manifest"
        self.due.assert_not_called()
        self.score_reports.assert_not_called()

    def test_one_persisted_call_per_team_with_that_teams_ids_only(self) -> None:
        self._candidates((1, "a"), (2, "b"), (1, "novec-c"))

        result = score_inbox_reports()

        assert sorted(
            (call.args[0], call.args[1], call.kwargs["persist"]) for call in self.score_reports.call_args_list
        ) == [(1, ["a", "novec-c"], True), (2, ["b"], True)]
        assert all(
            call.kwargs["serving"] is self.serving and call.kwargs["capture"] is self.capture
            for call in self.score_reports.call_args_list
        )
        assert (self.load_serving_set.call_count, self.capture_scopes) == (1, 1)
        assert (result.candidates, result.scored, result.no_vector, result.teams, result.failed_teams) == (
            3,
            2,
            1,
            2,
            0,
        )
        assert (result.manifest_version, result.skipped_reason) == (MANIFEST, None)

    def test_one_teams_error_is_counted_and_the_next_team_is_scored(self) -> None:
        self._candidates((1, "a"), (2, "b"))
        self.failing_teams[1] = RuntimeError("boom")

        result = score_inbox_reports()

        assert (result.scored, result.teams, result.failed_teams) == (1, 2, 1)

    def test_teams_left_when_the_time_budget_runs_out_are_deferred_to_the_next_tick(self) -> None:
        self._candidates((1, "a"), (2, "b"), (3, "c"))
        clock = [0.0]
        self._patch(sweep, "time", new=SimpleNamespace(monotonic=lambda: clock[0]))

        def slow_first_team(team_id: int, report_ids: list[str], **kwargs: Any) -> list:
            clock[0] += sweep._TIME_BUDGET.total_seconds()
            return self._outcomes(team_id, report_ids, **kwargs)

        self.score_reports.side_effect = slow_first_team

        result = score_inbox_reports()

        assert [call.args[0] for call in self.score_reports.call_args_list] == [1]
        assert (result.scored, result.teams, result.failed_teams, result.deferred_teams) == (1, 3, 0, 2)

    @parameterized.expand(
        [("scoring_error", ScoringError("no served score")), ("served_model_load", ModelLoadError("no booster"))]
    )
    def test_a_scoring_error_aborts_the_run(self, _name: str, error: Exception) -> None:
        self._candidates((1, "a"), (2, "b"))
        self.failing_teams[1] = error

        with self.assertRaises(type(error)):
            score_inbox_reports()

        assert self.score_reports.call_count == 1
