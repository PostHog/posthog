import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models.team.team import Team

from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.task_run_artefacts import append_task_run_artefact, record_implementation_task
from products.signals.backend.temporal.signal_queries import ReportSignalMeta

if TYPE_CHECKING:
    from products.tasks.backend.models import Task, TaskRun


class TestSignalReportDeleteAPI(APIBaseTest):
    def _url(self, report_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signals/reports/"
        if report_id:
            return f"{base}{report_id}/"
        return base

    def _create_report(self, team=None, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=3,
            total_weight=1.5,
        )

    # --- Delete ---

    @parameterized.expand(
        [
            ("from_ready", SignalReport.Status.READY, status.HTTP_202_ACCEPTED),
            ("from_potential", SignalReport.Status.POTENTIAL, status.HTTP_202_ACCEPTED),
            ("from_candidate", SignalReport.Status.CANDIDATE, status.HTTP_202_ACCEPTED),
            # Suppressed reports are excluded from the base queryset when no status
            # filter is supplied, so detail delete returns 404.
            ("from_suppressed", SignalReport.Status.SUPPRESSED, status.HTTP_404_NOT_FOUND),
            ("from_failed", SignalReport.Status.FAILED, status.HTTP_202_ACCEPTED),
        ]
    )
    def test_delete_report_starts_deletion_workflow(self, _name, initial_status, expected_status):
        report = self._create_report(report_status=initial_status)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == expected_status
        if expected_status == status.HTTP_202_ACCEPTED:
            assert response.json() == {"status": "deletion_started", "report_id": str(report.id)}
        report.refresh_from_db()
        if expected_status == status.HTTP_202_ACCEPTED:
            assert report.status == SignalReport.Status.DELETED
        else:
            assert report.status == initial_status

    def test_deleted_report_excluded_from_list(self):
        report = self._create_report()
        self.client.delete(self._url(str(report.id)))
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert all(r["id"] != str(report.id) for r in response.json()["results"])

    def test_delete_other_teams_report_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = self._create_report(team=other_team)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_delete_already_deleted_report_returns_404(self):
        report = self._create_report(report_status=SignalReport.Status.DELETED)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestSignalReportListAPI(APIBaseTest):
    """GET list/retrieve: `priority` from actionability artefacts; `ordering` (comma-separated, e.g. `status,-total_weight`)."""

    def _list_url(self, **query) -> str:
        base = f"/api/projects/{self.team.id}/signals/reports/"
        if not query:
            return base
        return f"{base}?{urlencode(query)}"

    def _create_report(self, **kwargs) -> SignalReport:
        defaults = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Test report",
            "summary": "Test summary",
            "signal_count": 3,
            "total_weight": 1.5,
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def _priority_artefact(
        self,
        report: SignalReport,
        *,
        priority: str | None,
        created_at=None,
    ) -> SignalReportArtefact:
        payload = {"explanation": "x"}
        if priority is not None:
            payload["priority"] = priority
        art = SignalReportArtefact(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps(payload),
        )
        if created_at is not None:
            art.save()
            SignalReportArtefact.objects.filter(pk=art.pk).update(created_at=created_at)
            art.refresh_from_db()
        else:
            art.save()
        return art

    def _actionability_artefact(self, report: SignalReport, *, actionability: str) -> SignalReportArtefact:
        payload = {"explanation": "x", "actionability": actionability, "already_addressed": False}
        art = SignalReportArtefact(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps(payload),
        )
        art.save()
        return art

    def _maybe_actionability_artefact(
        self, report: SignalReport, actionability: str | None
    ) -> SignalReportArtefact | None:
        if actionability is None:
            return None
        return self._actionability_artefact(report, actionability=actionability)

    # --- priority ---

    def test_list_includes_priority_from_priority_artefact(self):
        report = self._create_report()
        self._priority_artefact(report, priority="P2")

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        row = next(r for r in rows if r["id"] == str(report.id))
        assert row["priority"] == "P2"

    def test_list_uses_latest_priority_artefact_by_created_at(self):
        report = self._create_report()
        now = timezone.now()
        self._priority_artefact(report, priority="P3", created_at=now - timedelta(hours=1))
        self._priority_artefact(report, priority="P1", created_at=now)

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] == "P1"

    def test_list_priority_null_without_priority_artefact(self):
        report = self._create_report()

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] is None

    @parameterized.expand(
        [
            ("invalid_json", "not-json{"),
            ("json_null", "null"),
            ("json_array", "[]"),
            ("non_string_priority", json.dumps({"priority": 2})),
            ("missing_priority_key", json.dumps({"choice": "immediately_actionable"})),
        ]
    )
    def test_list_priority_null_for_bad_artefact_content(self, _name, content):
        report = self._create_report()
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=content,
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] is None

    def test_retrieve_includes_priority(self):
        report = self._create_report()
        self._priority_artefact(report, priority="P0")

        url = f"/api/projects/{self.team.id}/signals/reports/{report.id}/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == "P0"

    # --- priority filter ---

    @parameterized.expand(
        [
            ("single", "P1", {"P1"}),
            ("multiple", "P0,P2", {"P0", "P2"}),
            ("case_insensitive", "p1", {"P1"}),
        ]
    )
    def test_filter_by_priority(self, _name, query_value, expected_priorities):
        reports_by_priority = {
            "P0": self._create_report(title="P0 report"),
            "P1": self._create_report(title="P1 report"),
            "P2": self._create_report(title="P2 report"),
        }
        for priority, report in reports_by_priority.items():
            self._priority_artefact(report, priority=priority)

        response = self.client.get(self._list_url(priority=query_value))
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(reports_by_priority[p].id) for p in expected_priorities}

    def test_filter_excludes_reports_without_priority(self):
        self._create_report(title="No priority")
        r_p1 = self._create_report(title="P1 report")
        self._priority_artefact(r_p1, priority="P1")

        response = self.client.get(self._list_url(priority="P1"))
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(r_p1.id)}

    @parameterized.expand(
        [
            ("out_of_range", "P9"),
            ("garbage", "not-a-priority"),
            ("mixed_valid_and_invalid", "P0,P9"),
        ]
    )
    def test_filter_priority_invalid_value_returns_400(self, _name, raw):
        response = self.client.get(self._list_url(priority=raw))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "priority"
        assert body["code"] == "invalid_input"

    def test_filter_priority_combines_with_ordering(self):
        r_p2 = self._create_report(title="P2 report")
        r_p0 = self._create_report(title="P0 report")
        r_p1 = self._create_report(title="P1 report")
        self._priority_artefact(r_p2, priority="P2")
        self._priority_artefact(r_p0, priority="P0")
        self._priority_artefact(r_p1, priority="P1")

        response = self.client.get(self._list_url(priority="P0,P2", ordering="priority"))
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids == [str(r_p0.id), str(r_p2.id)]

    # --- status filter ---

    def test_filter_by_resolved_status(self):
        resolved = self._create_report(title="Resolved", status=SignalReport.Status.RESOLVED)
        self._create_report(title="Ready", status=SignalReport.Status.READY)

        response = self.client.get(self._list_url(status="resolved"))
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(resolved.id)}

    @parameterized.expand(
        [
            ("garbage", "bogus_status"),
            ("mixed_valid_and_invalid", "ready,bogus_status"),
            ("deleted_not_filterable", "deleted"),
        ]
    )
    def test_filter_status_invalid_value_returns_400(self, _name, raw):
        response = self.client.get(self._list_url(status=raw))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "status"
        assert body["code"] == "invalid_input"

    # --- ordering ---

    def test_ready_before_candidate_even_if_candidate_has_higher_weight(self):
        """With `status` first, stage rank dominates; then `-total_weight`."""
        low_ready = self._create_report(
            title="Ready",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        high_candidate = self._create_report(
            status=SignalReport.Status.CANDIDATE,
            title="Candidate",
            summary="s",
            signal_count=1,
            total_weight=99.0,
        )
        response = self.client.get(
            self._list_url(
                status="ready,candidate",
                ordering="status,-total_weight",
            )
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(low_ready.id)) < ids.index(str(high_candidate.id))

    def test_secondary_total_weight_within_same_status(self):
        light = self._create_report(
            title="A",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        heavy = self._create_report(
            title="B",
            summary="s",
            signal_count=1,
            total_weight=10.0,
        )
        response = self.client.get(
            self._list_url(
                status="ready",
                ordering="status,-total_weight",
            )
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(heavy.id)) < ids.index(str(light.id))

    def test_ordering_by_priority_sorts_p0_first(self):
        """priority ordering: P0 > P1 > P2 > P3 > P4 > null."""
        r_p3 = self._create_report(title="P3 report", summary="s", signal_count=1, total_weight=1.0)
        r_p1 = self._create_report(title="P1 report", summary="s", signal_count=1, total_weight=1.0)
        r_p0 = self._create_report(title="P0 report", summary="s", signal_count=1, total_weight=1.0)
        r_p2 = self._create_report(title="P2 report", summary="s", signal_count=1, total_weight=1.0)
        r_none = self._create_report(title="No priority", summary="s", signal_count=1, total_weight=1.0)
        r_p4 = self._create_report(title="P4 report", summary="s", signal_count=1, total_weight=1.0)
        self._priority_artefact(r_p3, priority="P3")
        self._priority_artefact(r_p1, priority="P1")
        self._priority_artefact(r_p0, priority="P0")
        self._priority_artefact(r_p2, priority="P2")
        self._priority_artefact(r_p4, priority="P4")

        response = self.client.get(self._list_url(status="ready", ordering="priority"))
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(r_p0.id)) < ids.index(str(r_p1.id))
        assert ids.index(str(r_p1.id)) < ids.index(str(r_p2.id))
        assert ids.index(str(r_p2.id)) < ids.index(str(r_p3.id))
        assert ids.index(str(r_p3.id)) < ids.index(str(r_p4.id))
        assert ids.index(str(r_p4.id)) < ids.index(str(r_none.id))

    def test_ordering_skips_unknown_clause_keeps_valid_ones(self):
        """An unrecognized clause (e.g. a stale persisted field) is skipped, not fatal:
        the valid clauses still apply instead of silently reverting to the default order."""
        r_p1 = self._create_report(title="P1 report", summary="s", signal_count=1, total_weight=1.0)
        r_p3 = self._create_report(title="P3 report", summary="s", signal_count=1, total_weight=1.0)
        self._priority_artefact(r_p1, priority="P1")
        self._priority_artefact(r_p3, priority="P3")

        response = self.client.get(self._list_url(status="ready", ordering="bogus_field,priority"))
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(r_p1.id)) < ids.index(str(r_p3.id))

    def test_ordering_by_total_weight_only_crosses_status_rank(self):
        """Without `status`, `ordering=-total_weight` is a global sort by weight."""
        low_ready = self._create_report(
            title="Ready",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        high_candidate = self._create_report(
            status=SignalReport.Status.CANDIDATE,
            title="Candidate",
            summary="s",
            signal_count=1,
            total_weight=99.0,
        )
        response = self.client.get(
            self._list_url(
                status="ready,candidate",
                ordering="-total_weight",
            )
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(high_candidate.id)) < ids.index(str(low_ready.id))

    @parameterized.expand(
        [
            ("immediately_actionable_before_not_actionable", "immediately_actionable", "not_actionable"),
            ("requires_human_input_before_not_actionable", "requires_human_input", "not_actionable"),
            ("no_judgment_before_not_actionable", None, "not_actionable"),
        ]
    )
    def test_status_ordering_splits_ready_by_actionability(
        self, _name, left_actionability: str | None, right_actionability: str
    ):
        """`ordering=status` maps to pipeline_status_rank: actionable ready before not_actionable."""
        r_left = self._create_report(title="L", summary="s", signal_count=1, total_weight=1.0)
        r_right = self._create_report(title="R", summary="s", signal_count=1, total_weight=1.0)
        self._maybe_actionability_artefact(r_left, left_actionability)
        self._actionability_artefact(r_right, actionability=right_actionability)

        response = self.client.get(self._list_url(status="ready", ordering="status"))
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(r_left.id)) < ids.index(str(r_right.id))

    @parameterized.expand(
        [
            ("ready_not_actionable", SignalReport.Status.READY, "ready", "not_actionable", False),
            (
                "ready_immediately_actionable",
                SignalReport.Status.READY,
                "ready",
                "immediately_actionable",
                True,
            ),
            (
                "ready_requires_human_input",
                SignalReport.Status.READY,
                "ready",
                "requires_human_input",
                True,
            ),
            (
                "failed_immediately_actionable",
                SignalReport.Status.FAILED,
                "failed",
                "immediately_actionable",
                False,
            ),
        ]
    )
    def test_is_suggested_reviewer_matches_actionability(
        self,
        name: str,
        report_status: str,
        status_filter: str,
        actionability: str,
        expected_suggested: bool,
    ):
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid=f"github-test-suggested-{name}",
            extra_data={"login": "suggestedgh"},
        )
        report = self._create_report(status=report_status)
        self._actionability_artefact(report, actionability=actionability)
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "suggestedgh"}]),
        )

        response = self.client.get(self._list_url(status=status_filter))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["is_suggested_reviewer"] is expected_suggested

    def test_is_suggested_reviewer_true_when_no_actionability_judgment(self):
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid="github-test-suggested-no-judgment",
            extra_data={"login": "suggestedgh"},
        )
        report = self._create_report()
        # No actionability artefact — latest_actionability_value is NULL
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "suggestedgh"}]),
        )

        response = self.client.get(self._list_url(status="ready"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["is_suggested_reviewer"] is True

    def test_is_suggested_reviewer_uses_latest_reviewers_row(self):
        # suggested_reviewers is append-only: an older row listing the user must not keep them
        # flagged after a newer row drops them (latest-wins).
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid="github-test-latest-wins",
            extra_data={"login": "suggestedgh"},
        )
        report = self._create_report()
        self._actionability_artefact(report, actionability="immediately_actionable")
        old = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "suggestedgh"}]),
        )
        SignalReportArtefact.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=1))
        # Newer row no longer includes the user — the live reviewer set.
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "someoneelse"}]),
        )

        response = self.client.get(self._list_url(status="ready"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["is_suggested_reviewer"] is False

    # --- implementation_pr_url ---

    def _create_implementation_task_with_run(
        self, report: SignalReport, *, pr_url: str | None = None, output: dict | None = None
    ) -> "tuple[Task, TaskRun]":
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="Implementation task",
            description="Fix the bug",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        record_implementation_task(
            team_id=self.team.id,
            report_id=str(report.id),
            task_id=str(task.id),
        )
        run_output = output if output is not None else ({"pr_url": pr_url} if pr_url else None)
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            status=TaskRun.Status.COMPLETED,
            output=run_output,
        )
        return task, run

    def test_implementation_pr_url_present_when_task_has_pr(self):
        report = self._create_report()
        self._create_implementation_task_with_run(report, pr_url="https://github.com/org/repo/pull/42")

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] == "https://github.com/org/repo/pull/42"

    def test_retrieve_implementation_pr_url_present_when_task_has_pr(self):
        report = self._create_report()
        self._create_implementation_task_with_run(report, pr_url="https://github.com/org/repo/pull/42")

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["implementation_pr_url"] == "https://github.com/org/repo/pull/42"
        assert response.json()["implementation_pr_url"] == response.json()["implementation_pr_url"].strip('"')

    def test_implementation_pr_url_resolves_from_artefact_only_association(self):
        # A task associated purely via a task_run artefact (no SignalReportTask gate row, e.g. a
        # custom-agent run) still resolves its PR — the unified association covers both sources.
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        report = self._create_report()
        task = Task.objects.create(
            team=self.team, title="t", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="implementation",
            task_id=str(task.id),
        )
        assert not SignalReportTask.objects.filter(report=report).exists()
        TaskRun.objects.create(
            team=self.team,
            task=task,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/o/r/pull/7"},
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] == "https://github.com/o/r/pull/7"

    def test_implementation_pr_url_null_when_no_implementation_task(self):
        report = self._create_report()

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] is None

    def test_implementation_pr_url_null_when_output_has_no_pr_url(self):
        report = self._create_report()
        self._create_implementation_task_with_run(report, output={"commit_sha": "abc123"})

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] is None

    def test_implementation_pr_url_null_when_pr_url_is_empty_string(self):
        report = self._create_report()
        self._create_implementation_task_with_run(report, pr_url="")

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] is None

    def test_implementation_pr_url_uses_latest_task_run(self):
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        report = self._create_report()
        task = Task.objects.create(
            team=self.team,
            title="Implementation task",
            description="Fix the bug",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        record_implementation_task(
            team_id=self.team.id,
            report_id=str(report.id),
            task_id=str(task.id),
        )
        old_run = TaskRun.objects.create(
            team=self.team,
            task=task,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        # Force older created_at
        TaskRun.objects.filter(pk=old_run.pk).update(created_at=timezone.now() - timedelta(hours=1))
        TaskRun.objects.create(
            team=self.team,
            task=task,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/99"},
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["implementation_pr_url"] == "https://github.com/org/repo/pull/99"

    def test_fetches_implementation_pr_urls_for_current_report_page(self):
        report_with_pr = self._create_report(title="Report with PR")
        report_without_pr = self._create_report(title="Report without PR")
        self._create_implementation_task_with_run(report_with_pr, pr_url="https://github.com/org/repo/pull/42")
        self._create_implementation_task_with_run(report_without_pr, output={"commit_sha": "abc123"})

        result = fetch_implementation_pr_urls_for_reports([str(report_with_pr.id), str(report_without_pr.id)])

        assert result == {
            str(report_with_pr.id): "https://github.com/org/repo/pull/42",
        }

    def test_fetch_implementation_pr_urls_issues_constant_queries(self):
        # N+1 guard: association is batched across the page, so resolving PR urls for many reports
        # costs the same number of queries as for one. A per-report `associated_task_runs` loop
        # scaled at two queries per report (one artefact read + one gate-row read), the exact
        # regression this asserts against.
        def seed(count: int) -> list[str]:
            ids = []
            for i in range(count):
                report = self._create_report(title=f"PR report {i}")
                self._create_implementation_task_with_run(report, pr_url=f"https://github.com/org/repo/pull/{i}")
                ids.append(str(report.id))
            return ids

        single = seed(1)
        with CaptureQueriesContext(connection) as for_one:
            fetch_implementation_pr_urls_for_reports(single)
        baseline = len(for_one.captured_queries)

        page = single + seed(5)
        with CaptureQueriesContext(connection) as for_many:
            result = fetch_implementation_pr_urls_for_reports(page)

        assert len(result) == 6
        # Constant in the page size, and a small fixed cost (artefacts + gate rows + PR lookup).
        assert len(for_many.captured_queries) == baseline
        assert baseline <= 3

    # --- has_implementation_pr filter ---

    @parameterized.expand(
        [
            ("true_keeps_pr_reports", "true", "with_pr"),
            ("false_keeps_non_pr_reports", "false", "without_pr"),
        ]
    )
    def test_filter_has_implementation_pr(self, _name, query_value, expected):
        report_with_pr = self._create_report(title="Report with PR")
        report_without_pr = self._create_report(title="Report without PR")
        self._create_implementation_task_with_run(report_with_pr, pr_url="https://github.com/org/repo/pull/42")
        expected_id = str(report_with_pr.id if expected == "with_pr" else report_without_pr.id)

        response = self.client.get(self._list_url(has_implementation_pr=query_value))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {r["id"] for r in body["results"]} == {expected_id}
        # `count` is the true total (matches what a limit=1 count query returns).
        assert body["count"] == 1

    def test_filter_has_implementation_pr_ignores_empty_pr_url(self):
        report_empty_pr = self._create_report(title="Report with empty PR url")
        self._create_implementation_task_with_run(report_empty_pr, pr_url="")

        with_pr = self.client.get(self._list_url(has_implementation_pr="true"))
        assert with_pr.json()["count"] == 0
        without_pr = self.client.get(self._list_url(has_implementation_pr="false"))
        assert str(report_empty_pr.id) in {r["id"] for r in without_pr.json()["results"]}

    def test_filter_has_implementation_pr_absent_returns_all(self):
        report_with_pr = self._create_report(title="Report with PR")
        report_without_pr = self._create_report(title="Report without PR")
        self._create_implementation_task_with_run(report_with_pr, pr_url="https://github.com/org/repo/pull/42")

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert {str(report_with_pr.id), str(report_without_pr.id)} <= ids

    def test_filter_has_implementation_pr_count_via_limit_one(self):
        for i in range(3):
            report = self._create_report(title=f"PR report {i}")
            self._create_implementation_task_with_run(report, pr_url=f"https://github.com/org/repo/pull/{i}")
        self._create_report(title="No PR report")

        response = self.client.get(self._list_url(has_implementation_pr="true", limit=1))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 3
        assert len(body["results"]) == 1

    def test_filter_has_implementation_pr_empty_value_is_noop(self):
        report_with_pr = self._create_report(title="Report with PR")
        report_without_pr = self._create_report(title="Report without PR")
        self._create_implementation_task_with_run(report_with_pr, pr_url="https://github.com/org/repo/pull/42")

        response = self.client.get(self._list_url(has_implementation_pr=""))
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert {str(report_with_pr.id), str(report_without_pr.id)} <= ids

    @parameterized.expand([("garbage", "maybe"), ("number", "2")])
    def test_filter_has_implementation_pr_invalid_value_returns_400(self, _name, raw):
        response = self.client.get(self._list_url(has_implementation_pr=raw))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "has_implementation_pr"
        assert body["code"] == "invalid_input"

    # --- actionability filter ---

    def test_filter_actionability_single_value(self):
        actionable = self._create_report(title="Actionable")
        self._actionability_artefact(actionable, actionability="immediately_actionable")
        not_actionable = self._create_report(title="Not actionable")
        self._actionability_artefact(not_actionable, actionability="not_actionable")

        response = self.client.get(self._list_url(actionability="not_actionable"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {r["id"] for r in body["results"]} == {str(not_actionable.id)}
        assert body["count"] == 1

    def test_filter_actionability_multiple_values(self):
        immediate = self._create_report(title="Immediate")
        self._actionability_artefact(immediate, actionability="immediately_actionable")
        needs_input = self._create_report(title="Needs input")
        self._actionability_artefact(needs_input, actionability="requires_human_input")
        not_actionable = self._create_report(title="Not actionable")
        self._actionability_artefact(not_actionable, actionability="not_actionable")

        response = self.client.get(self._list_url(actionability="immediately_actionable,requires_human_input"))
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(immediate.id), str(needs_input.id)}

    def test_filter_actionability_excludes_reports_without_judgment(self):
        # A report with no actionability_judgment artefact (annotation is NULL) is excluded.
        unjudged = self._create_report(title="Unjudged")
        not_actionable = self._create_report(title="Not actionable")
        self._actionability_artefact(not_actionable, actionability="not_actionable")

        response = self.client.get(self._list_url(actionability="not_actionable"))
        ids = {r["id"] for r in response.json()["results"]}
        assert str(unjudged.id) not in ids
        assert str(not_actionable.id) in ids

    def test_filter_actionability_count_via_limit_one(self):
        for i in range(3):
            report = self._create_report(title=f"NA report {i}")
            self._actionability_artefact(report, actionability="not_actionable")
        actionable = self._create_report(title="Actionable")
        self._actionability_artefact(actionable, actionability="immediately_actionable")

        response = self.client.get(self._list_url(actionability="not_actionable", limit=1))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 3
        assert len(body["results"]) == 1

    def test_filter_actionability_absent_returns_all(self):
        a = self._create_report(title="A")
        self._actionability_artefact(a, actionability="immediately_actionable")
        b = self._create_report(title="B")
        self._actionability_artefact(b, actionability="not_actionable")

        response = self.client.get(self._list_url())
        ids = {r["id"] for r in response.json()["results"]}
        assert {str(a.id), str(b.id)} <= ids

    def test_filter_actionability_invalid_value_returns_400(self):
        response = self.client.get(self._list_url(actionability="maybe_later"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "actionability"
        assert body["code"] == "invalid_input"

    # --- source_products ---

    def test_source_products_defaults_to_empty_list(self):
        report = self._create_report()

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["source_products"] == []

    def test_source_products_empty_on_retrieve_without_signals(self):
        report = self._create_report()

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["source_products"] == []

    def test_source_products_present_on_retrieve(self):
        report = self._create_report()

        with patch(
            "products.signals.backend.views.fetch_source_products_for_reports",
            return_value={
                str(report.id): ReportSignalMeta(
                    source_products=["zendesk", "github"], scout_name="signals-scout-error-tracking"
                )
            },
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["source_products"] == ["zendesk", "github"]
        # scout_name flows from the ClickHouse meta through the view's map split into the serializer.
        assert response.json()["scout_name"] == "signals-scout-error-tracking"

    def test_source_products_present_on_signals_action(self):
        report = self._create_report()

        with (
            patch(
                "products.signals.backend.views.fetch_source_products_for_reports",
                return_value={str(report.id): ReportSignalMeta(source_products=["zendesk"], scout_name=None)},
            ),
            patch("products.signals.backend.views.fetch_signals_for_report_sync", return_value=[]),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/signals/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["report"]["source_products"] == ["zendesk"]

    def test_source_products_resilient_to_clickhouse_failure_on_retrieve(self):
        report = self._create_report()

        with patch(
            "products.signals.backend.views.fetch_source_products_for_reports",
            side_effect=Exception("clickhouse timeout"),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["source_products"] == []

    # --- suppressed report reachability ---
    #
    # Suppressed (dismissed) reports stay out of the list by default, but the inbox's
    # Dismissed tab needs to read them by ID (detail + evidence) and reopen them. Read
    # paths (retrieve, signals, state) are reachable; mutating-by-ID paths (delete,
    # reingest) deliberately are not, so they keep returning 404.

    def test_retrieve_serves_suppressed_report(self):
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(report.id)
        assert response.json()["status"] == SignalReport.Status.SUPPRESSED

    def test_signals_action_serves_suppressed_report(self):
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        with (
            patch(
                "products.signals.backend.views.fetch_source_products_for_reports",
                return_value={str(report.id): ReportSignalMeta(source_products=["zendesk"], scout_name=None)},
            ),
            patch("products.signals.backend.views.fetch_signals_for_report_sync", return_value=[]),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/signals/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["report"]["id"] == str(report.id)

    def test_list_excludes_suppressed_by_default(self):
        ready = self._create_report(status=SignalReport.Status.READY)
        suppressed = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert str(ready.id) in ids
        assert str(suppressed.id) not in ids

    def test_list_includes_suppressed_when_filtered(self):
        suppressed = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.get(self._list_url(status="suppressed"))

        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert str(suppressed.id) in ids

    def test_reingest_suppressed_report_returns_404(self):
        # reingest is a mutating-by-ID action, so a suppressed report stays unreachable
        # and 404s before any workflow is started (mirrors the delete contract).
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.post(f"/api/projects/{self.team.id}/signals/reports/{report.id}/reingest/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- legacy choice removal ---

    def test_actionability_null_for_legacy_choice_artefact(self):
        report = self._create_report()
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps({"choice": "immediately_actionable", "explanation": "x"}),
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["actionability"] is None

    # --- dismissal reason ---

    def _dismissal_artefact(
        self,
        report: SignalReport,
        *,
        reason: str | None,
        note: str = "",
        created_at=None,
    ) -> SignalReportArtefact:
        payload: dict = {"note": note, "user_id": None, "user_uuid": None}
        if reason is not None:
            payload["reason"] = reason
        art = SignalReportArtefact(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            content=json.dumps(payload),
        )
        art.save()
        if created_at is not None:
            SignalReportArtefact.objects.filter(pk=art.pk).update(created_at=created_at)
            art.refresh_from_db()
        return art

    @parameterized.expand(
        [
            # Known reason code with a note: both are surfaced verbatim.
            ("known_reason_with_note", "wontfix_intentional", "by design", "wontfix_intentional", "by design"),
            # Reason codes are client-owned, so an unrecognised code passes through;
            # an empty note collapses to null.
            ("unknown_reason_passes_through", "some_brand_new_code", "", "some_brand_new_code", None),
        ]
    )
    def test_list_surfaces_dismissal_reason_and_note(self, _name, reason, note, expected_reason, expected_note):
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)
        self._dismissal_artefact(report, reason=reason, note=note)

        response = self.client.get(self._list_url(status="suppressed"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["dismissal_reason"] == expected_reason
        assert row["dismissal_note"] == expected_note

    def test_list_dismissal_reason_null_without_artefact(self):
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.get(self._list_url(status="suppressed"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["dismissal_reason"] is None
        assert row["dismissal_note"] is None

    def test_list_uses_latest_dismissal_artefact_by_created_at(self):
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)
        self._dismissal_artefact(report, reason="report_unclear", created_at=timezone.now() - timedelta(days=1))
        self._dismissal_artefact(report, reason="analysis_wrong")

        response = self.client.get(self._list_url(status="suppressed"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["dismissal_reason"] == "analysis_wrong"


class TestAssociatedTaskRunsForReports(APIBaseTest):
    """`SignalReport.associated_task_runs_for_reports` — the batched, page-wide counterpart of
    `associated_task_runs` that backs the inbox list without an N+1."""

    def _create_report(self, **kwargs) -> SignalReport:
        defaults = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Test report",
            "summary": "Test summary",
            "signal_count": 1,
            "total_weight": 1.0,
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def _new_task(self) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=self.team, title="t", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )

    def test_empty_report_ids_returns_empty(self):
        assert SignalReport.associated_task_runs_for_reports(report_ids=[]) == {}

    def test_groups_by_report_and_omits_reports_without_runs(self):
        report_with_gate = self._create_report()
        report_with_artefact = self._create_report()
        report_without_runs = self._create_report()
        gate_task = self._new_task()
        artefact_task = self._new_task()
        record_implementation_task(team_id=self.team.id, report_id=str(report_with_gate.id), task_id=str(gate_task.id))
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report_with_artefact.id),
            product="signals",
            type="implementation",
            task_id=str(artefact_task.id),
        )

        result = SignalReport.associated_task_runs_for_reports(
            report_ids=[str(report_with_gate.id), str(report_with_artefact.id), str(report_without_runs.id)]
        )

        assert set(result.keys()) == {str(report_with_gate.id), str(report_with_artefact.id)}
        assert [run.task_id for run in result[str(report_with_gate.id)]] == [str(gate_task.id)]
        assert [run.task_id for run in result[str(report_with_artefact.id)]] == [str(artefact_task.id)]

    def test_matches_per_report_associated_task_runs(self):
        # Parity with the trusted per-report method across mixed association sources.
        gate_report = self._create_report()
        artefact_report = self._create_report()
        empty_report = self._create_report()
        gate_task = self._new_task()
        artefact_task = self._new_task()
        record_implementation_task(team_id=self.team.id, report_id=str(gate_report.id), task_id=str(gate_task.id))
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(artefact_report.id),
            product="signals",
            type="implementation",
            task_id=str(artefact_task.id),
        )

        report_ids = [str(gate_report.id), str(artefact_report.id), str(empty_report.id)]
        batched = SignalReport.associated_task_runs_for_reports(
            report_ids=report_ids, product="signals", type="implementation"
        )

        for report_id in report_ids:
            per_report = SignalReport.associated_task_runs(
                report_id=report_id, product="signals", type="implementation"
            )
            assert batched.get(report_id, []) == per_report

    def test_respects_product_and_type_filters(self):
        report = self._create_report()
        impl_task = self._new_task()
        other_task = self._new_task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="implementation",
            task_id=str(impl_task.id),
        )
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="investigation",
            task_id=str(other_task.id),
        )

        result = SignalReport.associated_task_runs_for_reports(
            report_ids=[str(report.id)], product="signals", type="implementation"
        )

        assert [run.task_id for run in result[str(report.id)]] == [str(impl_task.id)]

    def test_scopes_by_team_id(self):
        report = self._create_report()
        task = self._new_task()
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        assert SignalReport.associated_task_runs_for_reports(report_ids=[str(report.id)], team_id=other_team.id) == {}
        assert str(report.id) in SignalReport.associated_task_runs_for_reports(
            report_ids=[str(report.id)], team_id=self.team.id
        )


class TestSignalReportSuppressionAPI(APIBaseTest):
    def _state_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/state/"

    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
        )

    @parameterized.expand(
        [
            # name, body, expected_final_status, expected_reason, expected_note (None = no artefact)
            (
                "suppress_without_dismissal_creates_no_artefact",
                {"state": "suppressed"},
                SignalReport.Status.SUPPRESSED,
                None,
                None,
            ),
            (
                "suppress_with_reason_and_note",
                {
                    "state": "suppressed",
                    "dismissal_reason": "wontfix_intentional",
                    "dismissal_note": "this is intentional behavior, see RFC-123",
                },
                SignalReport.Status.SUPPRESSED,
                "wontfix_intentional",
                "this is intentional behavior, see RFC-123",
            ),
            (
                "suppress_with_only_note",
                {"state": "suppressed", "dismissal_note": "free-form note"},
                SignalReport.Status.SUPPRESSED,
                None,
                "free-form note",
            ),
            (
                "suppress_with_other_reason",
                {"state": "suppressed", "dismissal_reason": "other", "dismissal_note": "edge case"},
                SignalReport.Status.SUPPRESSED,
                "other",
                "edge case",
            ),
            (
                "snooze_with_reason_and_note",
                {
                    "state": "potential",
                    "dismissal_reason": "wontfix_irrelevant",
                    "dismissal_note": "snoozing for now",
                },
                SignalReport.Status.POTENTIAL,
                "wontfix_irrelevant",
                "snoozing for now",
            ),
        ]
    )
    def test_state_transition_with_dismissal(self, _name, body, expected_final_status, expected_reason, expected_note):
        report = self._create_report()
        response = self.client.post(
            self._state_url(str(report.id)), data=json.dumps(body), content_type="application/json"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == expected_final_status

        # The response serializes the report after the dismissal artefact is written, so it must
        # reflect the just-saved reason/note — not a stale prefetch evaluated before the write.
        assert response.json()["dismissal_reason"] == expected_reason
        assert response.json()["dismissal_note"] == expected_note

        artefacts = list(
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL)
        )
        if expected_reason is None and expected_note is None:
            assert artefacts == []
            return

        assert len(artefacts) == 1
        content = json.loads(artefacts[0].content)
        assert content["reason"] == expected_reason
        assert content["note"] == expected_note
        assert content["user_id"] == self.user.id
        assert content["user_uuid"] == str(self.user.uuid)

    def test_state_transition_response_includes_source_products(self):
        report = self._create_report()

        with patch(
            "products.signals.backend.views.fetch_source_products_for_reports",
            return_value={str(report.id): ReportSignalMeta(source_products=["zendesk"], scout_name=None)},
        ):
            response = self.client.post(
                self._state_url(str(report.id)),
                data=json.dumps({"state": "suppressed"}),
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["source_products"] == ["zendesk"]

    def test_state_transition_resilient_to_clickhouse_failure(self):
        # A ClickHouse hiccup during best-effort enrichment must not 500 an already-committed
        # state change — the transition is persisted and the response degrades to empty.
        report = self._create_report()

        with patch(
            "products.signals.backend.views.fetch_source_products_for_reports",
            side_effect=Exception("clickhouse timeout"),
        ):
            response = self.client.post(
                self._state_url(str(report.id)),
                data=json.dumps({"state": "suppressed"}),
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["source_products"] == []
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED

    @parameterized.expand(
        [
            (
                "oversized_dismissal_note",
                {"state": "suppressed", "dismissal_reason": "other", "dismissal_note": "x" * 4001},
            ),
            # Reason codes are now constrained to the canonical inbox set, so invented codes are rejected.
            (
                "non_canonical_dismissal_reason",
                {"state": "suppressed", "dismissal_reason": "some_brand_new_code"},
            ),
        ]
    )
    def test_state_transition_rejects_invalid_dismissal(self, _name, body):
        report = self._create_report()
        response = self.client.post(
            self._state_url(str(report.id)), data=json.dumps(body), content_type="application/json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL
        ).exists()

    def test_rejects_unknown_state(self):
        report = self._create_report()
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "ready"}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_snooze_for_delays_repromotion(self):
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=5
        )
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "potential", "snooze_for": 10}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.POTENTIAL
        assert report.signals_at_run == 15

    @parameterized.expand([("zero", 0), ("negative", -1), ("too_large", 100_001)])
    def test_snooze_for_out_of_bounds_rejected(self, _name, snooze_for):
        report = self._create_report()
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "potential", "snooze_for": snooze_for}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_internal_transition_kwargs_are_not_injectable(self):
        # Callers must not be able to reach internal transition_to kwargs through the body.
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=5, total_weight=9.0
        )
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps(
                {
                    "state": "potential",
                    "reset_weight": True,
                    "error": "injected",
                    "signals_at_run_increment": 999,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.POTENTIAL
        # None of the injected kwargs took effect.
        assert report.total_weight == 9.0
        assert report.error is None
        assert report.signals_at_run == 0

    def test_can_reopen_suppressed_report(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        response = self.client.post(
            self._state_url(str(report.id)),
            data=json.dumps({"state": "potential"}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.POTENTIAL

    @parameterized.expand(
        [
            # prior status before archiving, expected status after restore
            ("ready", SignalReport.Status.READY, SignalReport.Status.READY),
            ("pending_input", SignalReport.Status.PENDING_INPUT, SignalReport.Status.PENDING_INPUT),
            ("resolved", SignalReport.Status.RESOLVED, SignalReport.Status.RESOLVED),
            ("failed", SignalReport.Status.FAILED, SignalReport.Status.FAILED),
            # In-flight / pre-research states have no live workflow, so restore re-enters the pipeline.
            ("potential", SignalReport.Status.POTENTIAL, SignalReport.Status.POTENTIAL),
            ("candidate", SignalReport.Status.CANDIDATE, SignalReport.Status.POTENTIAL),
            ("in_progress", SignalReport.Status.IN_PROGRESS, SignalReport.Status.POTENTIAL),
        ]
    )
    def test_restore_returns_report_to_pre_suppression_status(self, _name, prior_status, expected_restored_status):
        report = SignalReport.objects.create(team=self.team, status=prior_status, title="t", summary="s")

        suppress = self.client.post(
            self._state_url(str(report.id)), data=json.dumps({"state": "suppressed"}), content_type="application/json"
        )
        assert suppress.status_code == status.HTTP_200_OK, suppress.json()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        assert report.status_before_suppression == prior_status

        restore = self.client.post(
            self._state_url(str(report.id)), data=json.dumps({"state": "potential"}), content_type="application/json"
        )
        assert restore.status_code == status.HTTP_200_OK, restore.json()
        report.refresh_from_db()
        assert report.status == expected_restored_status
        assert report.status_before_suppression is None

    def test_restore_preserves_title_and_summary(self):
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Original title", summary="Original summary"
        )
        self.client.post(
            self._state_url(str(report.id)), data=json.dumps({"state": "suppressed"}), content_type="application/json"
        )
        self.client.post(
            self._state_url(str(report.id)), data=json.dumps({"state": "potential"}), content_type="application/json"
        )
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        assert report.title == "Original title"
        assert report.summary == "Original summary"


class TestAvailableReviewersAPI(APIBaseTest):
    """GET signals/reports/available_reviewers/: returns every eligible org member (no cap), with server-side search."""

    def setUp(self):
        super().setUp()
        # The over-threshold report is throttled via the cache; clear it so each test starts fresh.
        cache.clear()

    def _url(self, **query) -> str:
        base = f"/api/projects/{self.team.id}/signals/reports/available_reviewers/"
        if not query:
            return base
        return f"{base}?{urlencode(query)}"

    def _fake_user(self, n: int) -> SimpleNamespace:
        return SimpleNamespace(
            uuid=uuid.UUID(int=n),
            first_name=f"User{n:04d}",
            last_name="Tester",
            email=f"user{n:04d}@example.com",
        )

    def _login_map(self, count: int) -> dict[str, SimpleNamespace]:
        return {f"gh{n}": self._fake_user(n) for n in range(count)}

    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_returns_all_members_without_cap(self, mock_map):
        # 250 > the old hard cap of 100: every member must come back now.
        mock_map.return_value = self._login_map(250)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 250

    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_search_query_filters_server_side(self, mock_map):
        mock_map.return_value = self._login_map(250)
        response = self.client.get(self._url(query="User0123"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert next(iter(body.values()))["email"] == "user0123@example.com"

    @patch("products.signals.backend.views.capture_exception")
    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_no_exception_captured_under_threshold(self, mock_map, mock_capture):
        mock_map.return_value = self._login_map(50)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        mock_capture.assert_not_called()

    @patch("products.signals.backend.views.capture_exception")
    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_exception_captured_over_threshold(self, mock_map, mock_capture):
        mock_map.return_value = self._login_map(1201)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1201
        mock_capture.assert_called_once()

    @patch("products.signals.backend.views.capture_exception")
    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_threshold_capture_deduplicated_across_requests(self, mock_map, mock_capture):
        # Repeated popover opens for the same over-threshold org must report at most once.
        mock_map.return_value = self._login_map(1201)
        for _ in range(3):
            assert self.client.get(self._url()).status_code == status.HTTP_200_OK
        mock_capture.assert_called_once()

    @patch("products.signals.backend.views.capture_exception")
    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_threshold_not_triggered_by_search_requests(self, mock_map, mock_capture):
        # A search-as-you-type request must not spam the threshold capture.
        mock_map.return_value = self._login_map(1201)
        response = self.client.get(self._url(query="User0001"))
        assert response.status_code == status.HTTP_200_OK
        mock_capture.assert_not_called()

    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_empty_org_returns_empty(self, mock_map):
        mock_map.return_value = {}
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {}

    @patch("products.signals.backend.views.get_org_member_github_login_to_user_map")
    def test_missing_team_map_returns_empty(self, mock_map):
        # The helper returns None for an unknown team; the view coalesces it to an empty result.
        mock_map.return_value = None
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {}


class TestSignalReportBulkStateAPI(APIBaseTest):
    def _bulk_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/bulk-state/"

    def _create_report(self, team=None, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
        )

    def _post(self, body: dict):
        return self.client.post(self._bulk_url(), data=json.dumps(body), content_type="application/json")

    def test_bulk_suppress_transitions_all_reports(self):
        reports = [self._create_report() for _ in range(3)]
        ids = [str(r.id) for r in reports]

        response = self._post({"ids": ids, "state": "suppressed", "dismissal_reason": "wontfix_intentional"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["transitioned_count"] == 3
        assert body["skipped_count"] == 0
        assert body["failed_count"] == 0
        assert body["not_found_count"] == 0
        # Results are in request order, each carrying the post-transition status.
        assert [row["id"] for row in body["results"]] == ids
        assert all(row["outcome"] == "transitioned" for row in body["results"])
        assert all(row["status"] == SignalReport.Status.SUPPRESSED for row in body["results"])

        for report in reports:
            report.refresh_from_db()
            assert report.status == SignalReport.Status.SUPPRESSED
            artefacts = SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL
            )
            assert artefacts.count() == 1
            assert json.loads(artefacts.get().content)["reason"] == "wontfix_intentional"

    def test_bulk_skips_disallowed_transitions_but_processes_the_rest(self):
        ready = self._create_report(report_status=SignalReport.Status.READY)
        # POTENTIAL -> POTENTIAL is not an allowed transition, so it comes back as `skipped`.
        already_potential = self._create_report(report_status=SignalReport.Status.POTENTIAL)

        response = self._post({"ids": [str(ready.id), str(already_potential.id)], "state": "potential"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["transitioned_count"] == 1
        assert body["skipped_count"] == 1
        outcomes = {row["id"]: row["outcome"] for row in body["results"]}
        assert outcomes[str(ready.id)] == "transitioned"
        assert outcomes[str(already_potential.id)] == "skipped"

        ready.refresh_from_db()
        assert ready.status == SignalReport.Status.POTENTIAL

    def test_bulk_reports_not_found_for_unknown_and_other_team_ids(self):
        mine = self._create_report()
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_teams_report = self._create_report(team=other_team)
        missing_id = "00000000-0000-0000-0000-000000000000"

        response = self._post({"ids": [str(mine.id), str(other_teams_report.id), missing_id], "state": "suppressed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["transitioned_count"] == 1
        assert body["not_found_count"] == 2
        outcomes = {row["id"]: row["outcome"] for row in body["results"]}
        assert outcomes[str(mine.id)] == "transitioned"
        # Another team's report is invisible (IDOR boundary) — reported as not_found, never touched.
        assert outcomes[str(other_teams_report.id)] == "not_found"
        assert outcomes[missing_id] == "not_found"

        other_teams_report.refresh_from_db()
        assert other_teams_report.status == SignalReport.Status.READY

    def test_bulk_deduplicates_ids_preserving_order(self):
        first = self._create_report()
        second = self._create_report()
        ids = [str(first.id), str(second.id), str(first.id)]

        response = self._post({"ids": ids, "state": "suppressed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [row["id"] for row in body["results"]] == [str(first.id), str(second.id)]
        assert body["transitioned_count"] == 2

    def test_bulk_restore_reaches_suppressed_reports(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        report.status_before_suppression = SignalReport.Status.READY
        report.save(update_fields=["status_before_suppression"])

        response = self._post({"ids": [str(report.id)], "state": "potential"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["transitioned_count"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @parameterized.expand(
        [
            ("empty_ids", {"ids": [], "state": "suppressed"}),
            ("missing_ids", {"state": "suppressed"}),
            ("too_many_ids", {"ids": [f"00000000-0000-0000-0000-{i:012d}" for i in range(101)], "state": "suppressed"}),
            (
                "invalid_reason",
                {"ids": ["00000000-0000-0000-0000-000000000001"], "state": "suppressed", "dismissal_reason": "made_up"},
            ),
            ("invalid_state", {"ids": ["00000000-0000-0000-0000-000000000001"], "state": "ready"}),
            ("non_uuid_id", {"ids": ["not-a-uuid"], "state": "suppressed"}),
        ]
    )
    def test_bulk_rejects_invalid_requests(self, _name, body):
        response = self._post(body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


class TestSignalReportTaskAssociationViaArtefacts(APIBaseTest):
    """task_run artefacts ARE the task↔report association: associate-me defaults + the reports task_id filter."""

    def _artefacts_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/"

    def _create_report(self, team=None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=SignalReport.Status.READY,
            title="Report",
            summary="Summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_task(self, team=None) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=team or self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _associate(self, report: SignalReport, content: dict, **extra):
        return self.client.post(
            self._artefacts_url(str(report.id)),
            data=json.dumps({"artefact_type": "task_run", "content": content}),
            content_type="application/json",
            **extra,
        )

    def test_associate_task_by_body(self):
        report = self._create_report()
        task = self._create_task()

        response = self._associate(report, {"task_id": str(task.id)})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["content"]["task_id"] == str(task.id)
        # product/type default to the generic agent-run identifiers.
        assert body["content"]["product"] == "tasks"
        assert body["content"]["type"] == "agent_run"
        artefact = SignalReportArtefact.objects.get(id=body["id"])
        # The entry is attributed to the task it records.
        assert str(artefact.task_id) == str(task.id)

    def test_associate_is_idempotent(self):
        report = self._create_report()
        task = self._create_task()

        first = self._associate(report, {"task_id": str(task.id)})
        second = self._associate(report, {"task_id": str(task.id)})
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first.json()["id"]
        assert (
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN).count()
            == 1
        )

    def test_associate_with_custom_product_and_type(self):
        report = self._create_report()
        task = self._create_task()

        response = self._associate(report, {"task_id": str(task.id), "product": "billing", "type": "anomaly_scan"})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        artefact = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN)
        content = json.loads(artefact.content)
        assert content["product"] == "billing"
        assert content["type"] == "anomaly_scan"

    def test_associate_with_invalid_product_returns_400(self):
        report = self._create_report()
        task = self._create_task()

        response = self._associate(report, {"task_id": str(task.id), "product": "Not Valid!"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN
        ).exists()

    def test_associate_defaults_to_header_task(self):
        # "Associate me with this report" — empty content, the agent's own task comes from the header.
        report = self._create_report()
        task = self._create_task()

        response = self._associate(report, {}, headers={"X-PostHog-Task-Id": str(task.id)})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        artefact = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN)
        assert json.loads(artefact.content)["task_id"] == str(task.id)
        assert str(artefact.task_id) == str(task.id)

    def test_associate_without_task_returns_400(self):
        report = self._create_report()
        response = self._associate(report, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_associate_foreign_team_task_returns_400(self):
        report = self._create_report()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        foreign_task = self._create_task(team=other_team)

        response = self._associate(report, {"task_id": str(foreign_task.id)})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportArtefact.objects.filter(report=report).exists()

    def test_associate_on_deleted_report_returns_404(self):
        report = self._create_report()
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])
        task = self._create_task()

        response = self._associate(report, {"task_id": str(task.id)})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_reports_list_filters_by_task_id(self):
        report = self._create_report()
        other_report = self._create_report()
        task = self._create_task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="tasks",
            type="agent_run",
            task_id=str(task.id),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?task_id={task.id}")
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {str(report.id)}
        assert str(other_report.id) not in ids

    def test_reports_list_rejects_malformed_task_id(self):
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?task_id=not-a-uuid")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestSignalReportLegacyTaskArtefactList(APIBaseTest):
    """The artefact list surfaces legacy `SignalReportTask` rows as synthetic `task_run` artefacts so
    research / implementation associations show up before the backfill has converted the gate rows."""

    def _artefacts_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/"

    def _create_report(self, team=None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=SignalReport.Status.READY,
            title="Report",
            summary="Summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_task(self, team=None) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=team or self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _task_runs(self, report_id: str) -> list[dict]:
        response = self.client.get(self._artefacts_url(report_id))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return [a for a in response.json()["results"] if a["type"] == "task_run"]

    @parameterized.expand(
        [
            ("research", "signals", "research"),
            ("implementation", "signals", "implementation"),
            ("repo_selection", "signals", "repo_selection"),
            (None, "tasks", "agent_run"),
            ("link-only", "tasks", "agent_run"),
        ]
    )
    def test_legacy_task_surfaces_as_synthetic_task_run(self, relationship, expected_product, expected_type):
        report = self._create_report()
        task = self._create_task()
        report_task = SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=relationship
        )

        task_runs = self._task_runs(str(report.id))
        assert len(task_runs) == 1
        artefact = task_runs[0]
        assert artefact["id"] == str(report_task.id)
        assert str(artefact["task_id"]) == str(task.id)
        assert artefact["content"]["task_id"] == str(task.id)
        assert artefact["content"]["product"] == expected_product
        assert artefact["content"]["type"] == expected_type

    def test_real_task_run_artefact_wins_over_legacy_row(self):
        report = self._create_report()
        task = self._create_task()
        # Both the gate row and the real artefact exist for the same task: only the real one shows.
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship="implementation")
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="implementation",
            task_id=str(task.id),
        )

        task_runs = self._task_runs(str(report.id))
        assert len(task_runs) == 1
        # The persisted artefact id is a real row, not the gate row's id.
        assert SignalReportArtefact.objects.filter(id=task_runs[0]["id"]).exists()

    def test_legacy_rows_are_not_persisted(self):
        report = self._create_report()
        task = self._create_task()
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship="research")

        self._task_runs(str(report.id))
        # Listing must not write the synthetic artefacts — the backfill owns that.
        assert not SignalReportArtefact.objects.filter(report=report).exists()

    def test_synthetic_rows_count_and_interleave_chronologically(self):
        report = self._create_report()
        older_task = self._create_task()
        newer_task = self._create_task()
        # A real artefact dated between the two legacy rows, so a correct merge interleaves by time.
        older = SignalReportTask.objects.create(team=self.team, report=report, task=older_task, relationship="research")
        SignalReportTask.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(hours=2))
        middle = append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="repo_selection",
            task_id=str(self._create_task().id),
        )
        SignalReportArtefact.objects.filter(id=middle.id).update(created_at=timezone.now() - timedelta(hours=1))
        newer = SignalReportTask.objects.create(
            team=self.team, report=report, task=newer_task, relationship="implementation"
        )

        response = self.client.get(self._artefacts_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        # count covers the real artefact plus both synthetic legacy rows.
        assert body["count"] == 3
        # Default order is newest-first; the legacy rows land at their own timestamps, not appended last.
        ids_newest_first = [a["id"] for a in body["results"]]
        assert ids_newest_first == [str(newer.id), str(middle.id), str(older.id)]

    def test_legacy_rows_do_not_cross_reports(self):
        report = self._create_report()
        other_report = self._create_report()
        task = self._create_task()
        SignalReportTask.objects.create(team=self.team, report=other_report, task=task, relationship="research")

        # The gate row belongs to `other_report`, so `report`'s log stays empty.
        assert self._task_runs(str(report.id)) == []
        assert len(self._task_runs(str(other_report.id))) == 1


class TestSignalReportContentUpdateAPI(APIBaseTest):
    def _url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/"

    def _create_report(self, team=None, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title="Original title",
            summary="Original summary",
            signal_count=3,
            total_weight=1.5,
        )

    def test_update_title_and_summary(self):
        report = self._create_report()
        response = self.client.patch(
            self._url(str(report.id)),
            data={"title": "New title", "summary": "New summary"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["title"] == "New title"
        assert body["summary"] == "New summary"
        report.refresh_from_db()
        assert report.title == "New title"
        assert report.summary == "New summary"

    def test_update_title_only_leaves_summary_unchanged(self):
        report = self._create_report()
        response = self.client.patch(self._url(str(report.id)), data={"title": "Just the title"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.title == "Just the title"
        assert report.summary == "Original summary"

    def test_update_summary_trims_whitespace(self):
        report = self._create_report()
        response = self.client.patch(self._url(str(report.id)), data={"summary": "  padded  "}, format="json")
        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.summary == "padded"

    def test_update_with_no_editable_fields_is_rejected(self):
        report = self._create_report()
        response = self.client.patch(self._url(str(report.id)), data={}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        report.refresh_from_db()
        assert report.title == "Original title"

    @parameterized.expand([("blank_title", "title", ""), ("blank_summary", "summary", "")])
    def test_update_rejects_blank_values(self, _name, field, value):
        report = self._create_report()
        response = self.client.patch(self._url(str(report.id)), data={field: value}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_rejects_overlong_title(self):
        report = self._create_report()
        response = self.client.patch(self._url(str(report.id)), data={"title": "x" * 301}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_other_teams_report_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = self._create_report(team=other_team)
        response = self.client.patch(self._url(str(report.id)), data={"title": "Nope"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        report.refresh_from_db()
        assert report.title == "Original title"

    def test_update_deleted_report_returns_404(self):
        report = self._create_report(report_status=SignalReport.Status.DELETED)
        response = self.client.patch(self._url(str(report.id)), data={"title": "Nope"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_suppressed_report_returns_404(self):
        # Suppressed reports are hidden from mutating-by-id actions unless an explicit status
        # filter asks for them, matching the delete/reingest contract.
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        response = self.client.patch(self._url(str(report.id)), data={"title": "Nope"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def _artefacts_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/"

    def _create_task(self, team=None) -> "Task":
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=team or self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _artefacts(self, report: SignalReport, artefact_type: str) -> list[SignalReportArtefact]:
        return list(report.artefacts.filter(type=artefact_type).order_by("created_at"))

    def test_update_title_records_title_change_artefact(self):
        report = self._create_report()
        self.client.patch(self._url(str(report.id)), data={"title": "New title"}, format="json")

        artefacts = self._artefacts(report, SignalReportArtefact.ArtefactType.TITLE_CHANGE)
        assert len(artefacts) == 1
        content = json.loads(artefacts[0].content)
        assert content == {"old_title": "Original title", "new_title": "New title"}
        # Attributed to the requesting user, not a task, when no task header is present.
        assert artefacts[0].created_by_id == self.user.id
        assert artefacts[0].task_id is None

    def test_update_summary_records_summary_change_artefact(self):
        report = self._create_report()
        self.client.patch(self._url(str(report.id)), data={"summary": "New summary"}, format="json")

        artefacts = self._artefacts(report, SignalReportArtefact.ArtefactType.SUMMARY_CHANGE)
        assert len(artefacts) == 1
        content = json.loads(artefacts[0].content)
        assert content == {"old_summary": "Original summary", "new_summary": "New summary"}

    def test_update_both_records_one_artefact_per_field(self):
        report = self._create_report()
        self.client.patch(
            self._url(str(report.id)),
            data={"title": "New title", "summary": "New summary"},
            format="json",
        )
        assert len(self._artefacts(report, SignalReportArtefact.ArtefactType.TITLE_CHANGE)) == 1
        assert len(self._artefacts(report, SignalReportArtefact.ArtefactType.SUMMARY_CHANGE)) == 1

    def test_no_op_edit_records_no_artefact(self):
        # Setting a field to its current value isn't a change, so it leaves no edit-history entry.
        report = self._create_report()
        response = self.client.patch(
            self._url(str(report.id)),
            data={"title": "Original title", "summary": "New summary"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert self._artefacts(report, SignalReportArtefact.ArtefactType.TITLE_CHANGE) == []
        assert len(self._artefacts(report, SignalReportArtefact.ArtefactType.SUMMARY_CHANGE)) == 1

    def test_edit_attributed_to_task_when_header_present(self):
        # Mirrors the other artefact-writing paths: an agent's task header overrides user attribution.
        report = self._create_report()
        task = self._create_task()
        response = self.client.patch(
            self._url(str(report.id)),
            data={"title": "Agent title"},
            format="json",
            headers={"X-PostHog-Task-Id": str(task.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        artefacts = self._artefacts(report, SignalReportArtefact.ArtefactType.TITLE_CHANGE)
        assert len(artefacts) == 1
        assert str(artefacts[0].task_id) == str(task.id)
        assert artefacts[0].created_by_id is None

    @parameterized.expand([("title_change",), ("summary_change",)])
    def test_change_artefacts_are_read_only_via_artefact_api(self, artefact_type):
        # Edit-history artefacts are system-generated; the generic artefact write API must refuse
        # them so a caller can't fabricate edits that never happened.
        report = self._create_report()
        response = self.client.post(
            self._artefacts_url(str(report.id)),
            data=json.dumps({"artefact_type": artefact_type, "content": {}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "read-only" in response.json()["error"]
