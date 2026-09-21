import json
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.pr_origin import PullRequestOrigin, place_origin_section
from products.signals.backend.signal_metadata import OriginSignal
from products.signals.backend.task_run_artefacts import record_implementation_task

# Task ORM model needed to build a cross-product fixture; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task

SECTION = "<!-- posthog-self-driving-origin:r1 -->\n## Origin\n\n- new\n<!-- /posthog-self-driving-origin:r1 -->"


class TestPlaceOriginSection(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "below_problem",
                "## Problem\n\n- broken\n\n## Changes\n\n- fixed\n",
                f"## Problem\n\n- broken\n\n{SECTION}\n\n## Changes\n\n- fixed\n",
            ),
            (
                "replaces_earlier_copy",
                "## Problem\n\n- broken\n\n<!-- posthog-self-driving-origin:r1 -->\n## Origin\n\n- old\n"
                "<!-- /posthog-self-driving-origin:r1 -->\n\n## Changes\n",
                f"## Problem\n\n- broken\n\n{SECTION}\n\n## Changes\n",
            ),
            (
                "appended_without_problem",
                "Fixes the thing.\n",
                f"Fixes the thing.\n\n{SECTION}\n",
            ),
        ]
    )
    def test_places_section(self, _name: str, body: str, expected: str) -> None:
        assert place_origin_section(body, report_id="r1", section=SECTION) == expected


class TestPullRequestOrigin(BaseTest):
    def _signal(self, source_product: str, source_id: str, scout_name: str = "") -> OriginSignal:
        return OriginSignal(
            source_product=source_product,
            source_id=source_id,
            scout_name=scout_name,
            ticket_number=0,
            timestamp=datetime(2026, 9, 15, 7, 3, tzinfo=UTC),
        )

    def test_renders_only_allowlisted_facts(self) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=3, total_weight=3.0
        )
        task = Task.objects.create(
            team=self.team, title="task", description="desc", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        record_implementation_task(
            team_id=self.team.id,
            report_id=str(report.id),
            task_id=str(task.id),
            automation_branch="posthog-self-driving/fix-abc123",
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            content=json.dumps(
                {
                    "signal_id": "s1",
                    "relevant_code_paths": ["ee/api/vercel/webhooks.py"],
                    "relevant_commit_hashes": {"not-a-sha": "junk", "a59c3290": "added the capture"},
                    "data_queried": "a customer's private details",
                    "verified": True,
                }
            ),
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"explanation": "a customer's private details", "priority": "P2"}),
        )
        signals = [
            self._signal("error_tracking", "01a0a561-54a4"),
            self._signal("error_tracking", "../../settings?x=1"),
            self._signal("error_tracking", "run:1:finding:2", scout_name="signals-scout-error-tracking"),
        ]

        with (
            patch("products.signals.backend.pr_origin.fetch_origin_signals_for_report", return_value=signals),
            patch("products.signals.backend.pr_origin.fetch_source_references_for_report", return_value=[]),
        ):
            section = PullRequestOrigin.for_report(
                team=self.team, report_id=str(report.id), task_id=str(task.id), repository="acme/web"
            ).render()

        project = f"/project/{self.team.id}"
        assert f"[issue 1](http://localhost:8010{project}/error_tracking/01a0a561-54a4)" in section
        assert "and 1 more" in section
        assert "settings?x=1" not in section
        assert "run:1:finding:2" not in section
        assert "- Scout: `signals-scout-error-tracking`" in section
        assert "- First signal: 2026-09-15" in section
        assert "[`a59c3290`](https://github.com/acme/web/commit/a59c3290)" in section
        assert "- Started by: auto-start, after the report was rated P2 and ready to fix" in section
        assert "private" not in section
