import json
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.pr_origin import (
    PullRequestOrigin,
    _scout_label,
    place_origin_section,
    write_origin_section,
)
from products.signals.backend.pull_request_body import BodyEditOutcome
from products.signals.backend.signal_metadata import OriginSource, SignalSourceReference
from products.signals.backend.task_run_artefacts import record_implementation_task

# Task ORM model needed to build a cross-product fixture; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun

SECTION = "<!-- posthog-self-driving-origin:r1 -->\n## Origin\n\n- new\n<!-- /posthog-self-driving-origin:r1 -->"
OTHER_REPORT = "<!-- posthog-self-driving-origin:r0 -->\n## Origin\n\n- other\n<!-- /posthog-self-driving-origin:r0 -->"


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
                "keeps_an_unmarked_origin_section",
                "## Problem\n\n- broken\n\n## Origin\n\nRequired by the template.\n\n## Changes\n",
                f"## Problem\n\n- broken\n\n{SECTION}\n\n## Origin\n\nRequired by the template.\n\n## Changes\n",
            ),
            (
                "second_report_keeps_the_first",
                f"## Problem\n\n- broken\n\n{OTHER_REPORT}\n\n## Changes\n",
                f"## Problem\n\n- broken\n\n{SECTION}\n\n{OTHER_REPORT}\n\n## Changes\n",
            ),
            (
                "fenced_heading_is_code",
                "## Problem\n\n```\n## Origin\n---\n```\n\n## Changes\n",
                f"## Problem\n\n```\n## Origin\n---\n```\n\n{SECTION}\n\n## Changes\n",
            ),
            (
                "indented_fence_with_longer_close",
                "## Problem\n\n  ```\n## Origin\n  `````\n\n## Changes\n",
                f"## Problem\n\n  ```\n## Origin\n  `````\n\n{SECTION}\n\n## Changes\n",
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


class TestScoutLabel(SimpleTestCase):
    @parameterized.expand(
        [
            ("canonical", "signals-scout-error-tracking", "`signals-scout-error-tracking`"),
            ("custom", "signals-scout-acme-payment-incident", "a custom scout"),
        ]
    )
    def test_names_only_shipped_scouts(self, _name: str, scout_name: str, expected: str) -> None:
        source = OriginSource(
            source_product="error_tracking",
            scout_name=scout_name,
            first_seen=datetime(2026, 9, 15, tzinfo=UTC),
            entity_ids=("run:1:finding:2",),
        )
        assert _scout_label([source]) == expected


class TestPullRequestOrigin(BaseTest):
    def _priority(self, report: SignalReport, priority: str) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"explanation": "a customer's private details", "priority": priority}),
        )

    def test_renders_only_allowlisted_facts(self) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=3, total_weight=3.0
        )
        task = Task.objects.create(
            team=self.team, title="task", description="desc", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        self._priority(report, "P2")
        record_implementation_task(
            team_id=self.team.id,
            report_id=str(report.id),
            task_id=str(task.id),
            automation_branch="posthog-self-driving/fix-abc123",
        )
        self._priority(report, "P0")
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps(
                [
                    {
                        "github_login": "someone",
                        "relevant_commits": [
                            {
                                "reason": "added the capture",
                                "sha": "a59c3290",
                                "url": "https://github.com/acme/web/commit/a59c3290fe9bb4d4",
                            },
                            {
                                "reason": "injected",
                                "sha": "a59c3290",
                                "url": "https://github.com/acme/web/commit/a59c3290)\n\n## Injected",
                            },
                            {
                                "reason": "elsewhere",
                                "sha": "bbbbbbbb",
                                "url": "https://github.com/acme/other/commit/bbbbbbbbcccc",
                            },
                        ],
                    }
                ]
            ),
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            content=json.dumps(
                {
                    "signal_id": "s1",
                    "relevant_code_paths": ["ee/api/vercel/webhooks.py"],
                    "relevant_commit_hashes": {
                        "not-a-sha": "junk",
                        "bbbbbbbb": "other repository",
                        "a59c3290": "added the capture",
                    },
                    "data_queried": "a customer's private details",
                    "verified": True,
                }
            ),
        )
        sources = [
            OriginSource(
                source_product="error_tracking",
                scout_name="",
                first_seen=datetime(2026, 9, 15, 7, 3, tzinfo=UTC),
                entity_ids=("01a0a561-54a4", "zz/../settings?x=1"),
            ),
            OriginSource(
                source_product="error_tracking",
                scout_name="signals-scout-error-tracking",
                first_seen=datetime(2026, 9, 16, tzinfo=UTC),
                entity_ids=("run:1:finding:2",),
            ),
        ]

        with (
            patch("products.signals.backend.pr_origin.fetch_origin_sources_for_report", return_value=sources),
            patch(
                "products.signals.backend.pr_origin.fetch_source_references_for_report",
                return_value=[
                    SignalSourceReference("github", "#12", "https://github.com/acme/web/issues/12"),
                    SignalSourceReference("github", "#3", "https://github.com/acme/private/issues/3"),
                    SignalSourceReference("linear", "ENG-1", "https://linear.app/acme/issue/ENG-1/secret-title"),
                ],
            ),
        ):
            section = PullRequestOrigin.for_report(
                team=self.team, report_id=str(report.id), task_id=str(task.id), repository="acme/web"
            ).render()

        project = f"/project/{self.team.id}"
        assert f"[issue 1](http://localhost:8010{project}/error_tracking/01a0a561-54a4)" in section
        assert "settings?x=1" not in section
        assert "run:1:finding:2" not in section
        assert "- Scout: `signals-scout-error-tracking`" in section
        assert "- First signal: 2026-09-15" in section
        assert "[`a59c3290`](https://github.com/acme/web/commit/a59c3290fe9bb4d4)" in section
        assert "bbbbbbbb" not in section
        assert "Injected" not in section
        assert "- Task started by: auto-start, after the report was rated P2 and ready to fix" in section
        assert "- Issues: [#12](https://github.com/acme/web/issues/12), GitHub issue, Linear issue" in section
        assert "private" not in section
        assert "secret-title" not in section
        assert "ENG-1" not in section

    @parameterized.expand([("verified", True, BodyEditOutcome.WRITTEN), ("unverified", False, BodyEditOutcome.FAILED)])
    def test_edits_only_a_webhook_confirmed_pull_request(
        self, _name: str, verified: bool, expected: BodyEditOutcome
    ) -> None:
        pr_url = "https://github.com/acme/web/pull/7"
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )
        task = Task.objects.create(
            team=self.team, title="task", description="desc", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        TaskRun.objects.create(
            team=self.team,
            task=task,
            state={"verified_pr_urls": [pr_url] if verified else []},
            output={"pr_url": pr_url},
        )

        with (
            patch("products.signals.backend.pr_origin.fetch_origin_sources_for_report", return_value=[]),
            patch("products.signals.backend.pr_origin.fetch_source_references_for_report", return_value=[]),
            patch.object(
                GitHubIntegration,
                "first_for_team_repository",
                return_value=GitHubIntegration.__new__(GitHubIntegration),
            ),
            patch.object(GitHubIntegration, "get_pull_request", return_value={"success": True, "body": ""}),
            patch.object(GitHubIntegration, "update_pull_request_body", return_value={"success": True}) as update,
        ):
            outcome = write_origin_section(
                team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), pr_url=pr_url
            )

        assert outcome == expected
        assert update.called is verified
