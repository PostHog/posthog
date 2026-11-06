import json
from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.enums import ReportPriority
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.priority import persisted_report_priority


class TestPersistedReportPriority(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )

    def _judge(self, content: str, *, age: timedelta = timedelta()) -> None:
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=content,
        )
        # Pin the order explicitly: two rows created in the same test can share a timestamp.
        SignalReportArtefact.objects.filter(pk=artefact.pk).update(created_at=timezone.now() - age)

    def _priority(self, *, before: timedelta = timedelta(seconds=1)) -> ReportPriority | None:
        return persisted_report_priority(
            team_id=self.team.id, report_id=str(self.report.id), before=timezone.now() + before
        )

    def test_latest_judgment_wins(self) -> None:
        # Re-research and the artefact API append judgments; a reader that takes the first one
        # routes on a priority the team already changed.
        self._judge(json.dumps({"explanation": "core flow broken", "priority": "P1"}), age=timedelta(minutes=5))
        self._judge(json.dumps({"explanation": "narrower than thought", "priority": "P3"}))

        assert self._priority() is ReportPriority.P3

    def test_judgments_after_the_cut_off_are_ignored(self) -> None:
        # The implementation agent can append a judgment through the artefact API; a reader without
        # the cut-off would let it lower the effort of its own review.
        self._judge(json.dumps({"explanation": "core flow broken", "priority": "P1"}), age=timedelta(minutes=5))
        self._judge(json.dumps({"explanation": "turned out minor", "priority": "P4"}))

        assert self._priority(before=-timedelta(minutes=1)) is ReportPriority.P1

    @parameterized.expand(
        [
            ("no_judgment", None),
            ("legacy_plain_text", "P1 because the checkout is broken"),
            ("unknown_priority", json.dumps({"explanation": "x", "priority": "P9"})),
        ]
    )
    def test_missing_or_unreadable_judgment_reads_as_none(self, _name: str, content: str | None) -> None:
        # Callers key routing on this; an exception here would fail the caller instead of letting
        # it fall back.
        if content is not None:
            self._judge(content)

        assert self._priority() is None

    def test_scoped_to_the_team(self) -> None:
        self._judge(json.dumps({"explanation": "x", "priority": "P0"}))
        other_team = Team.objects.create(organization=self.organization)

        assert (
            persisted_report_priority(
                team_id=other_team.id, report_id=str(self.report.id), before=timezone.now() + timedelta(seconds=1)
            )
            is None
        )
