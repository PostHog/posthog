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

    def _latest_reviewers(self, report: SignalReport) -> list:
        # suggested_reviewers is append-only: the current reviewers are the latest row's content.
        artefact = (
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
            )
            .order_by("-created_at")
            .first()
        )
        return json.loads(artefact.content) if artefact else []

    def _reviewers_count(self, report: SignalReport) -> int:
        return SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        ).count()

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

    def test_put_sets_full_list(self):
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

        stored = self._latest_reviewers(report)
        assert [r["github_login"] for r in stored] == ["bob", "carol"]
        assert all(r["relevant_commits"] == [] for r in stored)

    def test_put_appends_new_status_row_keeping_history(self):
        report = self._create_report()
        original = self._create_artefact(
            report,
            content=[{"github_login": "alice", "github_name": "Alice", "relevant_commits": []}],
        )

        response = self.client.put(
            self._detail_url(str(report.id), str(original.id)),
            data=json.dumps({"content": [{"github_login": "bob"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        # A new status row is appended; the original is preserved untouched (the log keeps history).
        assert self._reviewers_count(report) == 2
        original.refresh_from_db()
        assert [r["github_login"] for r in json.loads(original.content)] == ["alice"]

        new_id = response.json()["id"]
        assert new_id != str(original.id)
        new_row = SignalReportArtefact.objects.get(id=new_id)
        assert [r["github_login"] for r in json.loads(new_row.content)] == ["bob"]
        assert [r["github_login"] for r in self._latest_reviewers(report)] == ["bob"]

    def test_put_empty_list_clears_content(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert self._latest_reviewers(report) == []

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

        stored = {r["github_login"]: r for r in self._latest_reviewers(report)}
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
        stored = self._latest_reviewers(report)
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
        stored = self._latest_reviewers(report)
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
        stored = self._latest_reviewers(report)
        assert [r["github_login"] for r in stored] == ["alice", "bob"]

    def test_put_repeated_yields_same_current_reviewers(self):
        # Each PUT appends a new status row (the log grows), but identical bodies leave the
        # *current* reviewers (latest row) unchanged.
        report = self._create_report()
        artefact = self._create_artefact(report, content=[])
        body = json.dumps({"content": [{"github_login": "alice"}, {"github_login": "bob"}]})

        first = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=body,
            content_type="application/json",
        )
        assert first.status_code == status.HTTP_200_OK
        first_current = self._latest_reviewers(report)

        second = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=body,
            content_type="application/json",
        )
        assert second.status_code == status.HTTP_200_OK
        assert self._latest_reviewers(report) == first_current
        # Original + two appended rows.
        assert self._reviewers_count(report) == 3

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
            ("code_reference", SignalReportArtefact.ArtefactType.CODE_REFERENCE),
            ("code_diff", SignalReportArtefact.ArtefactType.CODE_DIFF),
            ("line_reference", SignalReportArtefact.ArtefactType.LINE_REFERENCE),
            ("pushed_branch", SignalReportArtefact.ArtefactType.PUSHED_BRANCH),
            ("task_run", SignalReportArtefact.ArtefactType.TASK_RUN),
            ("note", SignalReportArtefact.ArtefactType.NOTE),
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
        stored = self._latest_reviewers(report)
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
        stored = self._latest_reviewers(report)
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


_CODE_REFERENCE_CONTENT = {
    "file_path": "products/signals/backend/models.py",
    "start_line": 10,
    "end_line": 12,
    "contents": "class Foo:\n    pass\n",
    "relevance_note": "where it lives",
}


class TestSignalReportArtefactLogWriteViewSet(APIBaseTest):
    """The generic log-artefact write surface (POST / PATCH / DELETE).

    Distinct from the bespoke `suggested_reviewers` PUT path covered above.
    """

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

    # --- POST (create log artefact) ---

    def test_post_creates_log_artefact_and_returns_id(self):
        report = self._create_report()

        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "code_reference", "content": _CODE_REFERENCE_CONTENT}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["type"] == "code_reference"
        assert body["content"] == _CODE_REFERENCE_CONTENT
        assert body["created_at"] is not None

        artefact = SignalReportArtefact.objects.get(id=body["id"])
        assert artefact.report_id == report.id
        assert artefact.team_id == self.team.id
        assert json.loads(artefact.content) == _CODE_REFERENCE_CONTENT

    @parameterized.expand(
        [
            ("code_reference", _CODE_REFERENCE_CONTENT),
            ("code_diff", {"file_path": "a.py", "diff": "@@ -1 +1 @@", "relevance_note": "x"}),
            ("line_reference", {"file_path": "a.py", "line": 3, "note": "here"}),
            ("pushed_branch", {"repository": "PostHog/posthog", "branch": "fix/foo", "base_branch": "master"}),
            ("task_run", {"task_id": "abc", "relationship": "signals_research"}),
            ("note", {"note": "a free-form note"}),
        ]
    )
    def test_post_accepts_each_log_type(self, artefact_type, content):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": artefact_type, "content": content}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["type"] == artefact_type

    def test_post_log_artefacts_accumulate(self):
        report = self._create_report()
        for _ in range(3):
            response = self.client.post(
                self._list_url(str(report.id)),
                data=json.dumps({"artefact_type": "note", "content": {"note": "tick"}}),
                content_type="application/json",
            )
            assert response.status_code == status.HTTP_201_CREATED

        assert (
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.NOTE).count() == 3
        )

    @parameterized.expand(
        [
            ("safety_judgment",),
            ("actionability_judgment",),
            ("priority_judgment",),
            ("repo_selection",),
            ("suggested_reviewers",),
            ("signal_finding",),
            ("dismissal",),
            ("video_segment",),
        ]
    )
    def test_post_rejects_non_log_types(self, artefact_type):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": artefact_type, "content": {}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "log artefact" in response.json()["error"]

    def test_post_rejects_unknown_type(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "not_a_real_type", "content": {}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_post_rejects_scalar_content(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "note", "content": "not-an-object"}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_post_on_deleted_report_returns_404(self):
        report = self._create_report()
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])

        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "note", "content": {"note": "x"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_post_on_other_team_report_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)

        response = self.client.post(
            self._list_url(str(other_report.id)),
            data=json.dumps({"artefact_type": "note", "content": {"note": "x"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SignalReportArtefact.objects.filter(report=other_report).exists()

    # --- PATCH (update log artefact content) ---

    def test_patch_updates_log_artefact_content(self):
        report = self._create_report()
        artefact = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": "before"}),
        )

        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"note": "after"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["content"] == {"note": "after"}

        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "after"}
        assert artefact.updated_at is not None

    def test_patch_rejects_status_artefact(self):
        # suggested_reviewers is a status type — editable only via the bespoke PUT path.
        report = self._create_report()
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([]),
        )

        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"note": "x"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Only log artefacts" in response.json()["error"]

    def test_patch_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = SignalReportArtefact.add_log(
            team_id=other_team.id,
            report_id=str(other_report.id),
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": "x"}),
        )

        response = self.client.patch(
            self._detail_url(str(other_report.id), str(artefact.id)),
            data=json.dumps({"content": {"note": "y"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- DELETE (remove log artefact) ---

    def test_delete_removes_log_artefact(self):
        report = self._create_report()
        artefact = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            type=SignalReportArtefact.ArtefactType.CODE_DIFF,
            content=json.dumps({"file_path": "a.py", "diff": "d", "relevance_note": "r"}),
        )

        response = self.client.delete(self._detail_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalReportArtefact.objects.filter(id=artefact.id).exists()

    def test_delete_rejects_status_artefact(self):
        report = self._create_report()
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
            content=json.dumps({"choice": True, "explanation": "safe"}),
        )

        response = self.client.delete(self._detail_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReportArtefact.objects.filter(id=artefact.id).exists()

    def test_delete_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = SignalReportArtefact.add_log(
            team_id=other_team.id,
            report_id=str(other_report.id),
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": "x"}),
        )

        response = self.client.delete(self._detail_url(str(other_report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalReportArtefact.objects.filter(id=artefact.id).exists()

    def test_post_rejects_missing_artefact_type(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"content": []}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
