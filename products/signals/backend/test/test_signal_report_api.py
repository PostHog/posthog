import json
from datetime import timedelta
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.views import SignalReportViewSet
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
            ("not_actionable", "not_actionable", False),
            ("immediately_actionable", "immediately_actionable", True),
            ("requires_human_input", "requires_human_input", True),
        ]
    )
    def test_is_suggested_reviewer_matches_actionability(self, _name, actionability: str, expected_suggested: bool):
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid=f"github-test-suggested-{actionability}",
            extra_data={"login": "suggestedgh"},
        )
        report = self._create_report()
        self._actionability_artefact(report, actionability=actionability)
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "suggestedgh"}]),
        )

        response = self.client.get(self._list_url(status="ready"))
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

        viewset = SignalReportViewSet()
        viewset.team = self.team
        result = viewset._fetch_implementation_pr_urls_for_reports([str(report_with_pr.id), str(report_without_pr.id)])

        assert result == {
            str(report_with_pr.id): "https://github.com/org/repo/pull/42",
        }

    # --- source_products ---

    def test_source_products_defaults_to_empty_list(self):
        report = self._create_report()

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["source_products"] == []

    def test_source_products_empty_on_retrieve(self):
        report = self._create_report()

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["source_products"] == []

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
