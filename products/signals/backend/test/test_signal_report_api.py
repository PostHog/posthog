import json
from datetime import timedelta
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models.team.team import Team

from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
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

    # --- implementation_pr_url ---

    def _create_implementation_task_with_run(
        self, report: SignalReport, *, pr_url: str | None = None, output: dict | None = None
    ) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="Implementation task",
            description="Fix the bug",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        SignalReportTask.objects.create(
            team=self.team,
            report=report,
            task=task,
            relationship=SignalReportTask.Relationship.IMPLEMENTATION,
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
        report = self._create_report()
        task = Task.objects.create(
            team=self.team,
            title="Implementation task",
            description="Fix the bug",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        SignalReportTask.objects.create(
            team=self.team,
            report=report,
            task=task,
            relationship=SignalReportTask.Relationship.IMPLEMENTATION,
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
            return_value={str(report.id): ["zendesk", "github"]},
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["source_products"] == ["zendesk", "github"]

    def test_source_products_present_on_signals_action(self):
        report = self._create_report()

        with (
            patch(
                "products.signals.backend.views.fetch_source_products_for_reports",
                return_value={str(report.id): ["zendesk"]},
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
                return_value={str(report.id): ["zendesk"]},
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
            # The caller (PostHog Code) owns the set of valid reason codes; the API persists whatever it gets.
            (
                "suppress_accepts_arbitrary_reason",
                {"state": "suppressed", "dismissal_reason": "some_brand_new_code"},
                SignalReport.Status.SUPPRESSED,
                "some_brand_new_code",
                None,
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
            return_value={str(report.id): ["zendesk"]},
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
