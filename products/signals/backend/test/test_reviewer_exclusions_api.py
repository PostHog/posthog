import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership, User

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReviewerExclusion,
    SignalReviewerExclusionRevision,
)
from products.signals.backend.presentation.reviewer_exclusions import SignalReviewerExclusionViewSet
from products.signals.backend.reviewer_exclusions import create_exclusion


class TestReviewerExclusionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/signals/reviewer_exclusions/"
        self.teammate = User.objects.create(email="teammate@example.com")
        OrganizationMembership.objects.create(user=self.teammate, organization=self.organization)

    def _report_with_reviewers(self, *users: User) -> SignalReport:
        report = SignalReport.objects.create(team=self.team, status="ready", title="A report")
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(user.uuid)} for user in users]),
        )
        return report

    def _reviewer_uuids(self, report: SignalReport) -> list[str]:
        latest = (
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
            )
            .order_by("-created_at", "-id")
            .first()
        )
        assert latest is not None
        return [entry["user_uuid"] for entry in json.loads(latest.content)]

    @parameterized.expand(
        [
            ("retrieve", "get", ""),
            ("amend", "patch", ""),
            ("revoke", "post", "revoke/"),
        ]
    )
    def test_member_cannot_reach_another_members_instruction(self, _name: str, method: str, suffix: str) -> None:
        theirs = create_exclusion(
            team_id=self.team.id, actor_id=self.teammate.id, instruction="Off.", subject_user_uuid=self.teammate.uuid
        )

        response = getattr(self.client, method)(f"{self.url}{theirs.id}/{suffix}", {"instruction": "x"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self.url).json() == []
        theirs.refresh_from_db()
        assert (theirs.status, theirs.instruction) == (SignalReviewerExclusion.Status.ACTIVE, "Off.")

    def test_create_with_report_removes_the_member_then_saves_the_instruction(self) -> None:
        report = self._report_with_reviewers(self.user, self.teammate)

        response = self.client.post(
            self.url,
            {"instruction": "I moved teams.", "repository": "Org/App", "report_id": str(report.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert (body["instruction_saved"], body["report_removed"]) == (True, True)
        assert body["exclusion"]["repository"] == "org/app"
        assert self._reviewer_uuids(report) == [str(self.teammate.uuid)]
        exclusion = SignalReviewerExclusion.objects.for_team(self.team.id).get(id=body["exclusion"]["id"])
        assert (exclusion.subject_user_uuid, exclusion.created_by_id) == (self.user.uuid, self.user.id)

    def test_failed_save_after_report_removal_is_partial_success_and_retry_saves(self) -> None:
        report = self._report_with_reviewers(self.user, self.teammate)
        payload = {"instruction": "I moved teams.", "report_id": str(report.id)}

        with patch(
            "products.signals.backend.presentation.reviewer_exclusions.create_exclusion",
            side_effect=RuntimeError("database unavailable"),
        ):
            failed = self.client.post(self.url, payload, format="json")

        assert failed.status_code == status.HTTP_207_MULTI_STATUS
        body = failed.json()
        assert (body["instruction_saved"], body["report_removed"], body["exclusion"]) == (False, True, None)
        assert self._reviewer_uuids(report) == [str(self.teammate.uuid)]
        assert not SignalReviewerExclusion.objects.for_team(self.team.id).exists()

        retried = self.client.post(self.url, payload, format="json")

        assert retried.status_code == status.HTTP_201_CREATED
        assert retried.json()["instruction_saved"] is True
        assert SignalReviewerExclusion.objects.for_team(self.team.id).count() == 1

    def test_amend_then_revoke_keeps_history_and_leaves_reports_alone(self) -> None:
        created = self.client.post(self.url, {"instruction": "Off billing."}, format="json").json()["exclusion"]
        detail = f"{self.url}{created['id']}/"
        report = self._report_with_reviewers(self.teammate)

        amended = self.client.patch(detail, {"repository": "org/app", "path_prefix": "src/billing"}, format="json")
        assert amended.status_code == status.HTTP_200_OK
        assert (amended.json()["path_prefix"], amended.json()["revision"]) == ("src/billing", 2)

        revoked = self.client.post(f"{detail}revoke/")
        assert revoked.status_code == status.HTTP_200_OK
        assert revoked.json()["status"] == SignalReviewerExclusion.Status.REVOKED

        assert self.client.patch(detail, {"instruction": "Back."}, format="json").status_code == 400
        assert self._reviewer_uuids(report) == [str(self.teammate.uuid)]
        assert list(
            SignalReviewerExclusionRevision.objects.for_team(self.team.id)
            .filter(exclusion_id=created["id"])
            .order_by("revision")
            .values_list("action", flat=True)
        ) == ["created", "revised", "revoked"]

    @parameterized.expand(
        [
            (f"{method}_{name}", method, area)
            for method in ("post", "patch")
            for name, area in [
                ("path_without_repository", {"path_prefix": "src"}),
                ("repository_url", {"repository": "https://github.com/org/app"}),
                ("repository_trailing_slash", {"repository": "org/app/"}),
                ("path_leading_slash", {"repository": "org/app", "path_prefix": "/src"}),
            ]
        ]
    )
    def test_area_that_can_never_match_is_rejected(self, _name: str, method: str, area: dict[str, str]) -> None:
        url = self.url
        if method == "patch":
            created = self.client.post(self.url, {"instruction": "Off."}, format="json").json()["exclusion"]
            url = f"{self.url}{created['id']}/"

        response = getattr(self.client, method)(url, {"instruction": "Off.", **area}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_amend_validates_the_area_against_a_concurrent_change(self) -> None:
        created = self.client.post(self.url, {"instruction": "Off.", "repository": "org/app"}, format="json").json()
        exclusion_id = created["exclusion"]["id"]
        load = SignalReviewerExclusionViewSet.get_object

        def load_then_clear_repository(view: SignalReviewerExclusionViewSet) -> SignalReviewerExclusion:
            stale = load(view)
            SignalReviewerExclusion.objects.for_team(self.team.id).filter(id=exclusion_id).update(repository="")
            return stale

        with patch.object(SignalReviewerExclusionViewSet, "get_object", load_then_clear_repository):
            response = self.client.patch(f"{self.url}{exclusion_id}/", {"path_prefix": "src/billing"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReviewerExclusion.objects.for_team(self.team.id).get(id=exclusion_id).path_prefix == ""
