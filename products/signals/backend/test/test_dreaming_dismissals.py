import json
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.dreaming.dismissals import (
    DismissalSummary,
    aggregate_dismissals,
    known_false_positive_memory_section,
    resolve_dismissal_since,
    summarize_dismissals_for_briefing,
)


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-dreaming-dismissals-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-dreaming-dismissals-team")


def _report(team: Team) -> SignalReport:
    return SignalReport.objects.create(team=team, status=SignalReport.Status.SUPPRESSED)


def _dismiss(team: Team, report: SignalReport, *, reason: str | None = None, note: str = "", created_at=None) -> None:
    payload: dict = {"note": note}
    if reason is not None:
        payload["reason"] = reason
    art = SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.DISMISSAL,
        content=json.dumps(payload),
    )
    if created_at is not None:
        SignalReportArtefact.objects.filter(pk=art.pk).update(created_at=created_at)


class TestDismissalAggregation:
    @pytest.mark.django_db
    def test_empty_when_no_dismissals(self, team):
        summary = aggregate_dismissals(team.id, last_run_at_iso=None)
        assert summary.is_empty
        assert summary.total == 0
        assert summary.by_reason == {}

    @pytest.mark.django_db
    def test_counts_by_reason(self, team):
        for _ in range(3):
            _dismiss(team, _report(team), reason="not_a_bug")
        _dismiss(team, _report(team), reason="duplicate")
        _dismiss(team, _report(team), reason="wont_fix")

        summary = aggregate_dismissals(team.id, last_run_at_iso=None)

        assert summary.total == 5
        assert summary.by_reason == {"not_a_bug": 3, "duplicate": 1, "wont_fix": 1}
        assert summary.top_reason == ("not_a_bug", 3)

    @pytest.mark.django_db
    def test_collects_representative_notes_deduped(self, team):
        _dismiss(team, _report(team), reason="not_a_bug", note="This is expected behavior")
        _dismiss(team, _report(team), reason="not_a_bug", note="This is expected behavior")  # dup
        _dismiss(team, _report(team), reason="duplicate", note="Already tracked elsewhere")

        summary = aggregate_dismissals(team.id, last_run_at_iso=None)

        assert "This is expected behavior" in summary.representative_notes
        assert "Already tracked elsewhere" in summary.representative_notes
        assert sum(1 for n in summary.representative_notes if n == "This is expected behavior") == 1

    @pytest.mark.django_db
    def test_latest_dismissal_per_report_counted_once(self, team):
        report = _report(team)
        _dismiss(team, report, reason="report_unclear", created_at=timezone.now() - timedelta(hours=2))
        _dismiss(team, report, reason="analysis_wrong")  # newer

        summary = aggregate_dismissals(team.id, last_run_at_iso=None)

        assert summary.total == 1
        # Newest-first ordering means the latest reason wins.
        assert summary.by_reason == {"analysis_wrong": 1}

    @pytest.mark.django_db
    def test_respects_since_window(self, team):
        old = _report(team)
        _dismiss(team, old, reason="not_a_bug", created_at=timezone.now() - timedelta(days=3))
        recent = _report(team)
        _dismiss(team, recent, reason="duplicate")

        since_iso = (timezone.now() - timedelta(hours=24)).isoformat()
        summary = aggregate_dismissals(team.id, last_run_at_iso=since_iso)

        assert summary.total == 1
        assert summary.by_reason == {"duplicate": 1}

    @pytest.mark.django_db
    def test_ignores_other_teams(self, team, organization):
        other_team = Team.objects.create(organization=organization, name="other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.SUPPRESSED)
        SignalReportArtefact.objects.create(
            team=other_team,
            report=other_report,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            content=json.dumps({"reason": "not_a_bug", "note": ""}),
        )
        _dismiss(team, _report(team), reason="duplicate")

        summary = aggregate_dismissals(team.id, last_run_at_iso=None)

        assert summary.total == 1
        assert summary.by_reason == {"duplicate": 1}

    @pytest.mark.django_db
    def test_malformed_content_skipped(self, team):
        report = _report(team)
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            content="not json{{{",
        )
        summary = aggregate_dismissals(team.id, last_run_at_iso=None)
        # The malformed artefact contributes nothing.
        assert summary.by_reason == {}

    @pytest.mark.django_db
    @patch("products.signals.backend.temporal.dreaming.dismissals.fetch_source_products_for_reports")
    def test_groups_by_source_product(self, mock_fetch, team):
        r1 = _report(team)
        r2 = _report(team)
        _dismiss(team, r1, reason="not_a_bug")
        _dismiss(team, r2, reason="not_a_bug")
        mock_fetch.return_value = {
            str(r1.id): ["error_tracking"],
            str(r2.id): ["error_tracking", "session_replay"],
        }

        summary = aggregate_dismissals(team.id, last_run_at_iso=None)

        assert summary.by_source_product == {"error_tracking": 2, "session_replay": 1}

    @pytest.mark.django_db
    @patch(
        "products.signals.backend.temporal.dreaming.dismissals.fetch_source_products_for_reports",
        side_effect=RuntimeError("clickhouse down"),
    )
    def test_source_grouping_failure_degrades_gracefully(self, _mock_fetch, team):
        _dismiss(team, _report(team), reason="not_a_bug")
        summary = aggregate_dismissals(team.id, last_run_at_iso=None)
        # Reason counts still land; source grouping is simply absent.
        assert summary.by_reason == {"not_a_bug": 1}
        assert summary.by_source_product == {}


class TestDismissalRendering:
    def _summary(self) -> DismissalSummary:
        return DismissalSummary(
            total=4,
            by_reason={"not_a_bug": 3, "duplicate": 1},
            by_source_product={"error_tracking": 3},
            representative_notes=("expected behavior", "already tracked"),
        )

    def test_briefing_lines_include_counts_and_notes(self):
        lines = summarize_dismissals_for_briefing(self._summary())
        joined = " ".join(lines)
        assert "4 report(s) dismissed" in joined
        assert "not_a_bug (3)" in joined
        assert "error_tracking (3)" in joined
        assert "expected behavior" in joined

    def test_briefing_lines_empty_for_empty_summary(self):
        empty = DismissalSummary(total=0, by_reason={}, by_source_product={}, representative_notes=())
        assert summarize_dismissals_for_briefing(empty) == []

    def test_memory_section_renders_reasons_and_sources(self):
        body = known_false_positive_memory_section(self._summary())
        assert body is not None
        assert "not_a_bug: 3" in body
        assert "error_tracking: 3" in body

    def test_memory_section_none_when_no_reasons(self):
        empty = DismissalSummary(total=2, by_reason={}, by_source_product={}, representative_notes=())
        assert known_false_positive_memory_section(empty) is None

    def test_resolve_since_uses_last_run(self):
        ts = (timezone.now() - timedelta(hours=5)).replace(microsecond=0)
        resolved = resolve_dismissal_since(ts.isoformat())
        assert resolved.replace(microsecond=0) == ts

    def test_resolve_since_defaults_to_24h(self):
        resolved = resolve_dismissal_since(None)
        delta = timezone.now() - resolved
        assert timedelta(hours=23) < delta < timedelta(hours=25)
