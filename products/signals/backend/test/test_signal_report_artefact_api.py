import json
import uuid

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.models import SignalReport, SignalReportArtefact


def _attach_github_login(user: User, login: str, *, uid: str | None = None) -> None:
    UserSocialAuth.objects.create(
        user=user,
        provider="github",
        uid=uid or f"gh-{login}",
        extra_data={"login": login},
    )


class TestSignalReportArtefactViewSet(APIBaseTest):
    def _list_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/"

    def _detail_url(self, report_id: str, artefact_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/{artefact_id}/"

    def _create_report(self, team: Team | None = None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_artefact(
        self,
        report: SignalReport,
        *,
        artefact_type: str = SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content: list | dict | None = None,
    ) -> SignalReportArtefact:
        if content is None:
            content = []
        return SignalReportArtefact.objects.create(
            team=report.team,
            report=report,
            type=artefact_type,
            content=json.dumps(content),
        )

    def _create_org_member(self, email: str, *, github_login: str | None = None) -> User:
        user = User.objects.create(email=email)
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        if github_login is not None:
            _attach_github_login(user, github_login, uid=f"gh-{email}")
        return user

    # --- GET list ---

    def test_list_returns_results_envelope(self):
        report = self._create_report()
        self._create_artefact(report, content=[{"github_login": "alice"}])
        self._create_artefact(
            report,
            artefact_type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content={"priority": "P1"},
        )

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 2
        assert len(data["results"]) == 2
        types = {row["type"] for row in data["results"]}
        assert types == {"suggested_reviewers", "priority_judgment"}

    def test_list_enriches_suggested_reviewers_with_user(self):
        member = self._create_org_member("alice@example.com", github_login="Alice")
        report = self._create_report()
        self._create_artefact(report, content=[{"github_login": "alice", "github_name": "Alice"}])

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        reviewer = rows[0]["content"][0]
        assert reviewer["github_login"] == "alice"
        assert reviewer["user"] is not None
        assert reviewer["user"]["uuid"] == str(member.uuid)
        assert reviewer["user"]["email"] == "alice@example.com"

    def test_list_unknown_login_returns_null_user(self):
        report = self._create_report()
        self._create_artefact(report, content=[{"github_login": "nobody"}])

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        assert rows[0]["content"][0]["user"] is None

    def test_list_scoped_to_report_and_team(self):
        report = self._create_report()
        other_report = self._create_report()
        self._create_artefact(report, content=[{"github_login": "alice"}])
        self._create_artefact(other_report, content=[{"github_login": "bob"}])

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_team_report = self._create_report(team=other_team)
        self._create_artefact(other_team_report, content=[{"github_login": "carol"}])

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["content"][0]["github_login"] == "alice"

    # --- GET retrieve ---

    def test_retrieve_returns_single_enriched_artefact(self):
        member = self._create_org_member("bob@example.com", github_login="bob")
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "bob"}])

        response = self.client.get(self._detail_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == str(artefact.id)
        assert body["content"][0]["user"]["uuid"] == str(member.uuid)

    def test_retrieve_artefact_from_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = self._create_artefact(other_report, content=[{"github_login": "alice"}])

        response = self.client.get(self._detail_url(str(other_report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- PUT (update) ---

    def test_put_replaces_full_list(self):
        report = self._create_report()
        artefact = self._create_artefact(
            report,
            content=[{"github_login": "alice", "github_name": "Alice", "relevant_commits": []}],
        )

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "Bob"}, {"github_login": "Carol"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert [r["github_login"] for r in stored] == ["bob", "carol"]
        assert all(r["relevant_commits"] == [] for r in stored)

    def test_put_empty_list_clears_content(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        assert json.loads(artefact.content) == []

    def test_put_preserves_relevant_commits_for_kept_entries(self):
        report = self._create_report()
        artefact = self._create_artefact(
            report,
            content=[
                {
                    "github_login": "alice",
                    "github_name": "Alice A.",
                    "relevant_commits": [{"sha": "abc123", "url": "u", "reason": "r"}],
                },
                {
                    "github_login": "bob",
                    "github_name": "Bob B.",
                    "relevant_commits": [{"sha": "def456", "url": "u2", "reason": "r2"}],
                },
            ],
        )

        # Keep alice (existing commits should survive), add a new reviewer dave (commits empty).
        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice"}, {"github_login": "dave"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        artefact.refresh_from_db()
        stored = {r["github_login"]: r for r in json.loads(artefact.content)}
        assert stored["alice"]["relevant_commits"] == [{"sha": "abc123", "url": "u", "reason": "r"}]
        assert stored["alice"]["github_name"] == "Alice A."  # carried over from prior
        assert stored["dave"]["relevant_commits"] == []
        assert "bob" not in stored

    def test_put_resolves_user_uuid_to_github_login(self):
        member = self._create_org_member("alice@example.com", github_login="AliceCase")
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"user_uuid": str(member.uuid)}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert len(stored) == 1
        assert stored[0]["github_login"] == "alicecase"

    def test_put_user_uuid_wins_over_supplied_github_login(self):
        member = self._create_org_member("alice@example.com", github_login="AliceCase")
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        # Client supplies both; server canonicalizes to the user's actual GitHub login.
        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"user_uuid": str(member.uuid), "github_login": "totally-different"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert stored[0]["github_login"] == "alicecase"

    def test_put_user_uuid_without_github_login_returns_400(self):
        # Org member without any linked GitHub identity.
        member = self._create_org_member("nogh@example.com", github_login=None)
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"user_uuid": str(member.uuid)}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not an org member" in response.json()["error"]

    def test_put_user_uuid_not_in_org_returns_400(self):
        # Random UUID not tied to anyone in this org.
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"user_uuid": str(uuid.uuid4())}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_entry_missing_both_login_and_uuid_returns_400(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_name": "orphan"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_content_must_be_a_list(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": "not-a-list"}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_dedupes_by_canonical_login_preserving_order(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps(
                {
                    "content": [
                        {"github_login": "Alice"},
                        {"github_login": "BOB"},
                        {"github_login": "alice"},  # duplicate after lowercase
                    ]
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert [r["github_login"] for r in stored] == ["alice", "bob"]

    def test_put_is_idempotent(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])
        body = json.dumps({"content": [{"github_login": "alice"}, {"github_login": "bob"}]})

        first = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=body,
            content_type="application/json",
        )
        assert first.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        first_content = artefact.content

        second = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=body,
            content_type="application/json",
        )
        assert second.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        assert artefact.content == first_content

    def test_put_response_is_enriched_with_user(self):
        member = self._create_org_member("alice@example.com", github_login="alice")
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["content"][0]["user"]["uuid"] == str(member.uuid)

    @parameterized.expand(
        [
            ("video_segment", SignalReportArtefact.ArtefactType.VIDEO_SEGMENT),
            ("safety_judgment", SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT),
            ("actionability_judgment", SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT),
            ("priority_judgment", SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT),
            ("signal_finding", SignalReportArtefact.ArtefactType.SIGNAL_FINDING),
            ("repo_selection", SignalReportArtefact.ArtefactType.REPO_SELECTION),
            ("dismissal", SignalReportArtefact.ArtefactType.DISMISSAL),
        ]
    )
    def test_put_rejects_non_suggested_reviewers_types(self, _name, artefact_type):
        report = self._create_report()
        artefact = self._create_artefact(report, artefact_type=artefact_type, content={})

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Only suggested_reviewers" in response.json()["error"]

    def test_put_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = self._create_artefact(other_report, content=[])

        response = self.client.put(
            self._detail_url(str(other_report.id), str(artefact.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_put_max_entries_enforced(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        too_many = [{"github_login": f"user{i}"} for i in range(11)]
        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": too_many}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_not_allowed(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_post_not_allowed(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_delete_not_allowed(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])
        response = self.client.delete(self._detail_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_list_excludes_artefacts_when_parent_report_deleted(self):
        report = self._create_report()
        self._create_artefact(report, content=[{"github_login": "alice"}])
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_put_on_deleted_report_artefact_returns_404(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_put_empty_github_name_clears_prior_value(self):
        # The pipeline stored a name; the client wants to clear it.
        report = self._create_report()
        artefact = self._create_artefact(
            report,
            content=[{"github_login": "alice", "github_name": "Alice A.", "relevant_commits": []}],
        )

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice", "github_name": ""}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert stored[0]["github_name"] == ""

    def test_put_omitted_github_name_carries_over_prior_value(self):
        # When the client doesn't mention github_name, keep what the pipeline had.
        report = self._create_report()
        artefact = self._create_artefact(
            report,
            content=[{"github_login": "alice", "github_name": "Alice A.", "relevant_commits": []}],
        )

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        artefact.refresh_from_db()
        stored = json.loads(artefact.content)
        assert stored[0]["github_name"] == "Alice A."

    def test_put_after_update_preserves_filter_jsonb_containment(self):
        """The list filter `?suggested_reviewers=<user-uuid>` reads the same field.

        Ensure that after a PUT, the canonical stored shape still matches the
        jsonb containment query the report list uses.
        """
        member = self._create_org_member("alice@example.com", github_login="alice")
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])

        put_response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "alice"}]}),
            content_type="application/json",
        )
        assert put_response.status_code == status.HTTP_200_OK

        list_url = f"/api/projects/{self.team.id}/signals/reports/?suggested_reviewers={member.uuid}"
        list_response = self.client.get(list_url)
        assert list_response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in list_response.json()["results"]}
        assert str(report.id) in ids
