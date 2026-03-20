import json
from datetime import timedelta
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestSignalReportDeleteAPI(APIBaseTest):
    def _url(self, report_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signal_reports/"
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
    """GET list/retrieve: `priority` from actionability artefacts; `ordering` (comma-separated, e.g. `pipeline,-total_weight`)."""

    def _list_url(self, **query) -> str:
        base = f"/api/projects/{self.team.id}/signal_reports/"
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

    def _actionability_artefact(
        self,
        report: SignalReport,
        *,
        priority: str | None,
        created_at=None,
    ) -> SignalReportArtefact:
        payload = {"choice": "immediately_actionable", "explanation": "x"}
        if priority is not None:
            payload["priority"] = priority
        art = SignalReportArtefact(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps(payload),
        )
        if created_at is not None:
            art.save()
            SignalReportArtefact.objects.filter(pk=art.pk).update(created_at=created_at)
            art.refresh_from_db()
        else:
            art.save()
        return art

    # --- priority ---

    def test_list_includes_priority_from_actionability_artefact(self):
        report = self._create_report()
        self._actionability_artefact(report, priority="P2")

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        row = next(r for r in rows if r["id"] == str(report.id))
        assert row["priority"] == "P2"

    def test_list_uses_latest_actionability_artefact_by_created_at(self):
        report = self._create_report()
        now = timezone.now()
        self._actionability_artefact(report, priority="P3", created_at=now - timedelta(hours=1))
        self._actionability_artefact(report, priority="P1", created_at=now)

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] == "P1"

    def test_list_priority_null_without_actionability_artefact(self):
        report = self._create_report()

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] is None

    def test_list_priority_null_when_artefact_json_invalid(self):
        report = self._create_report()
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content="not-json{",
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] is None

    def test_list_priority_null_when_priority_not_a_string(self):
        report = self._create_report()
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps({"priority": 2}),
        )

        response = self.client.get(self._list_url())
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.json()["results"] if r["id"] == str(report.id))
        assert row["priority"] is None

    def test_retrieve_includes_priority(self):
        report = self._create_report()
        self._actionability_artefact(report, priority="P0")

        url = f"/api/projects/{self.team.id}/signal_reports/{report.id}/"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == "P0"

    # --- ordering ---

    def test_ready_before_candidate_even_if_candidate_has_higher_weight(self):
        """With `pipeline` first, stage dominates; then `-total_weight`."""
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
                ordering="pipeline,-total_weight",
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
                ordering="pipeline,-total_weight",
            )
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(heavy.id)) < ids.index(str(light.id))

    def test_ordering_by_total_weight_only_crosses_pipeline(self):
        """Without `pipeline`, `ordering=-total_weight` is a global sort by weight."""
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
