import json
import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status
from social_django.models import UserSocialAuth

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.artefact_schemas import (
    CodeReference,
    NoteArtefact,
    Priority,
    PriorityAssessment,
    TaskRunArtefact,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact

# Task ORM model needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task  # tach-ignore


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

    def test_put_reviewers_re_evaluates_autostart(self):
        # Appending a reviewers status re-runs the (idempotent) auto-start evaluation on commit.
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])

        with patch(
            "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts",
            new_callable=AsyncMock,
        ) as mock_autostart:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.put(
                    self._detail_url(str(report.id), str(artefact.id)),
                    data=json.dumps({"content": [{"github_login": "alice"}, {"github_login": "bob"}]}),
                    content_type="application/json",
                )

        assert response.status_code == status.HTTP_200_OK
        mock_autostart.assert_awaited_once()
        assert mock_autostart.call_args.kwargs["report_id"] == str(report.id)
        assert mock_autostart.call_args.kwargs["team_id"] == self.team.id

    def test_put_reviewers_autostart_delegates_when_report_complete(self):
        # With actionability + repo + priority + reviewers all present, the reconstruction reaches
        # the actual autostart decision (delegated to maybe_autostart_implementation_task).
        report = self._create_report()
        self._create_artefact(
            report,
            artefact_type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content={"explanation": "e", "actionability": "immediately_actionable", "already_addressed": False},
        )
        self._create_artefact(
            report,
            artefact_type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
            content={"repository": "acme/repo", "reason": "r"},
        )
        self._create_artefact(
            report,
            artefact_type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content={"explanation": "e", "priority": "P1"},
        )
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])

        with patch(
            "products.signals.backend.auto_start.maybe_autostart_implementation_task",
            new_callable=AsyncMock,
        ) as mock_impl:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.put(
                    self._detail_url(str(report.id), str(artefact.id)),
                    data=json.dumps({"content": [{"github_login": "alice"}, {"github_login": "bob"}]}),
                    content_type="application/json",
                )

        assert response.status_code == status.HTTP_200_OK
        mock_impl.assert_awaited_once()
        kwargs = mock_impl.call_args.kwargs
        assert kwargs["repository"] == "acme/repo"
        assert {r["github_login"] for r in kwargs["reviewers_content"]} == {"alice", "bob"}
        # The edit must auto-start as the *editing* user (the API caller), never a named reviewer,
        # so one user can't run the agent under another's identity (reviewer impersonation).
        assert kwargs["triggering_user_id"] == self.user.id

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

    def test_put_reviewer_change_writes_activity_log_with_diff(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "bob"}, {"github_login": "carol"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        log = ActivityLog.objects.get(team_id=self.team.id, scope="SignalReport")
        assert log.activity == "suggested_reviewers_changed"
        assert str(log.item_id) == str(report.id)
        assert log.user == self.user
        assert log.detail is not None
        assert log.detail["name"] == "Test report"
        (change,) = log.detail["changes"]
        assert change["field"] == "suggested_reviewers"
        assert change["before"] == ["alice"]
        assert change["after"] == ["bob", "carol"]

    def test_put_same_reviewer_set_writes_no_activity_log(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}, {"github_login": "bob"}])

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "bob"}, {"github_login": "alice"}]}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert not ActivityLog.objects.filter(team_id=self.team.id, scope="SignalReport").exists()

    def test_put_task_attributed_reviewer_change_writes_no_activity_log(self):
        report = self._create_report()
        artefact = self._create_artefact(report, content=[{"github_login": "alice"}])
        task = Task.objects.create(
            team=self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

        response = self.client.put(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": [{"github_login": "bob"}]}),
            content_type="application/json",
            headers={"X-PostHog-Task-Id": str(task.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert not ActivityLog.objects.filter(team_id=self.team.id, scope="SignalReport").exists()

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
            ("commit", SignalReportArtefact.ArtefactType.COMMIT),
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

    def test_diff_with_non_dict_content_returns_400_not_500(self):
        # Log content is stored as arbitrary JSON; a non-object commit payload must not 500.
        report = self._create_report()
        artefact = self._create_artefact(
            report,
            artefact_type=SignalReportArtefact.ArtefactType.COMMIT,
            content=[1, 2, 3],
        )

        response = self.client.get(self._detail_url(str(report.id), str(artefact.id)) + "diff/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


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
            (
                "commit",
                {"repository": "PostHog/posthog", "branch": "fix/foo", "commit_sha": "abc123f", "message": "fix"},
            ),
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
            ("safety_judgment", {"choice": True}),
            (
                "actionability_judgment",
                {"explanation": "clear fix", "actionability": "immediately_actionable", "already_addressed": False},
            ),
            ("priority_judgment", {"explanation": "core flow broken", "priority": "P1"}),
            ("repo_selection", {"repository": "posthog/posthog", "reason": "where the code lives"}),
            (
                "signal_finding",
                {
                    "signal_id": "sig-1",
                    "relevant_code_paths": [],
                    "relevant_commit_hashes": {},
                    "data_queried": "events",
                    "verified": True,
                },
            ),
        ]
    )
    def test_post_accepts_status_and_finding_types(self, artefact_type, content):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": artefact_type, "content": content}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["type"] == artefact_type

    def test_post_status_type_is_latest_wins(self):
        report = self._create_report()
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PriorityAssessment(explanation="initial", priority=Priority.P3),
            attribution=ArtefactAttribution.system(),
        )

        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps(
                {
                    "artefact_type": "priority_judgment",
                    "content": {"explanation": "worse than thought", "priority": "P1"},
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        # Both rows survive (append-only); the newest is canonical on the report read.
        rows = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        assert rows.count() == 2
        report_response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert report_response.status_code == status.HTTP_200_OK
        assert report_response.json()["priority"] == "P1"

    def test_post_status_type_with_invalid_content_returns_400(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "priority_judgment", "content": {"priority": "P9"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_post_rejects_unknown_type(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "not_a_real_type", "content": {}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("empty", {}), ("populated", {"start": 1, "end": 2})])
    def test_post_rejects_read_only_video_segment_type(self, _name, content):
        # video_segment is a legacy permissive type with no real content validation (even {} passes),
        # so the write API must refuse it outright rather than persist an unvalidated payload.
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "video_segment", "content": content}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not SignalReportArtefact.objects.filter(report=report).exists()

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
            content=NoteArtefact(note="before"),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"note": "after"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["content"] == {"note": "after", "author": None}

        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "after", "author": None}
        assert artefact.updated_at is not None

    def test_patch_rejects_read_only_video_segment_type(self):
        # A legacy video_segment row stays readable, but the read-only type can't be edited via the API.
        report = self._create_report()
        legacy = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.VIDEO_SEGMENT,
            content=json.dumps({"start": 1, "end": 2}),
        )

        response = self.client.patch(
            self._detail_url(str(report.id), str(legacy.id)),
            data=json.dumps({"content": {"start": 9, "end": 9}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        legacy.refresh_from_db()
        assert json.loads(legacy.content) == {"start": 1, "end": 2}

    def test_patch_updates_status_artefact_validated_against_its_type(self):
        report = self._create_report()
        artefact = SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PriorityAssessment(explanation="initial", priority=Priority.P3),
            attribution=ArtefactAttribution.system(),
        )

        # Content not matching the row's type schema is rejected…
        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"note": "x"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # …while a valid edit lands and changes the canonical status (it's the latest row).
        response = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"explanation": "re-judged", "priority": "P0"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report_response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert report_response.json()["priority"] == "P0"

    def test_patch_task_run_cannot_drift_task_id_from_the_fk(self):
        report = self._create_report()
        task = Task.objects.create(
            team=self.team, title="t", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        other_task = Task.objects.create(
            team=self.team, title="o", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        artefact = SignalReportArtefact.append(
            team_id=self.team.id,
            report_id=str(report.id),
            content=TaskRunArtefact(task_id=str(task.id), product="signals", type="research"),
            attribution=ArtefactAttribution.from_task(str(task.id)),
        )

        # Editing content.task_id to a different task is rejected — the `task` FK is the association.
        drift = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"task_id": str(other_task.id), "product": "signals", "type": "research"}}),
            content_type="application/json",
        )
        assert drift.status_code == status.HTTP_400_BAD_REQUEST

        # Editing other fields while keeping the same task_id is fine.
        ok = self.client.patch(
            self._detail_url(str(report.id), str(artefact.id)),
            data=json.dumps({"content": {"task_id": str(task.id), "product": "signals", "type": "implementation"}}),
            content_type="application/json",
        )
        assert ok.status_code == status.HTTP_200_OK, ok.json()
        artefact.refresh_from_db()
        assert json.loads(artefact.content)["type"] == "implementation"
        assert str(artefact.task_id) == str(task.id)

    def test_patch_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = SignalReportArtefact.add_log(
            team_id=other_team.id,
            report_id=str(other_report.id),
            content=NoteArtefact(note="x"),
            attribution=ArtefactAttribution.from_user(self.user.id),
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
            content=CodeReference(file_path="a.py", start_line=1, end_line=1, contents="x", relevance_note="r"),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

        response = self.client.delete(self._detail_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalReportArtefact.objects.filter(id=artefact.id).exists()

    def test_delete_latest_status_artefact_reverts_canonical_to_previous(self):
        report = self._create_report()
        for priority, explanation in (("P3", "initial"), ("P1", "escalated")):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=PriorityAssessment(explanation=explanation, priority=Priority(priority)),
                attribution=ArtefactAttribution.system(),
            )
        latest = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        ).order_by("-created_at")[0]

        response = self.client.delete(self._detail_url(str(report.id), str(latest.id)))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalReportArtefact.objects.filter(id=latest.id).exists()

        report_response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert report_response.status_code == status.HTTP_200_OK
        assert report_response.json()["priority"] == "P3"

    def test_delete_other_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_report = self._create_report(team=other_team)
        artefact = SignalReportArtefact.add_log(
            team_id=other_team.id,
            report_id=str(other_report.id),
            content=NoteArtefact(note="x"),
            attribution=ArtefactAttribution.from_user(self.user.id),
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


class TestSignalReportArtefactAttribution(APIBaseTest):
    """Attribution of API writes: X-PostHog-Task-Id header → task, otherwise the requesting user."""

    def _list_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/"

    def _create_report(self, team: Team | None = None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_task(self, team: Team | None = None) -> Task:
        return Task.objects.create(
            team=team or self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _post_note(self, report: SignalReport, **extra):
        return self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "note", "content": {"note": "hello"}}),
            content_type="application/json",
            **extra,
        )

    def test_post_without_header_attributes_to_user(self):
        report = self._create_report()
        response = self._post_note(report)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        artefact = SignalReportArtefact.objects.get(id=response.json()["id"])
        assert artefact.created_by_id == self.user.id
        assert artefact.task_id is None
        assert response.json()["task_id"] is None

    def test_post_with_header_attributes_to_task(self):
        report = self._create_report()
        task = self._create_task()
        response = self._post_note(report, headers={"X-PostHog-Task-Id": str(task.id)})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        artefact = SignalReportArtefact.objects.get(id=response.json()["id"])
        assert str(artefact.task_id) == str(task.id)
        assert artefact.created_by_id is None
        assert response.json()["task_id"] == str(task.id)

    def test_post_with_foreign_team_task_header_returns_400(self):
        report = self._create_report()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        foreign_task = self._create_task(team=other_team)
        response = self._post_note(report, headers={"X-PostHog-Task-Id": str(foreign_task.id)})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportArtefact.objects.filter(report=report).exists()

    @parameterized.expand([("not-a-uuid",), ("0000",)])
    def test_post_with_malformed_task_header_returns_400(self, header_value):
        report = self._create_report()
        response = self._post_note(report, headers={"X-PostHog-Task-Id": header_value})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_post_with_unknown_task_header_returns_400(self):
        report = self._create_report()
        response = self._post_note(report, headers={"X-PostHog-Task-Id": str(uuid.uuid4())})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_exposes_created_by_and_task_id(self):
        report = self._create_report()
        assert self._post_note(report).status_code == status.HTTP_201_CREATED
        task = self._create_task()
        assert (
            self._post_note(report, headers={"X-PostHog-Task-Id": str(task.id)}).status_code == status.HTTP_201_CREATED
        )

        response = self.client.get(self._list_url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        by_task = {row["task_id"]: row for row in response.json()["results"]}
        user_row = by_task[None]
        task_row = by_task[str(task.id)]
        assert user_row["created_by"]["id"] == self.user.id
        assert task_row["created_by"] is None

    def test_dismissal_via_state_action_is_attributed(self):
        report = self._create_report()
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/reports/{report.id}/state/",
            data=json.dumps({"state": "suppressed", "dismissal_reason": "analysis_wrong"}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        dismissal = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL)
        assert dismissal.created_by_id == self.user.id

    def test_post_rejects_content_not_matching_type_schema(self):
        report = self._create_report()
        response = self.client.post(
            self._list_url(str(report.id)),
            data=json.dumps({"artefact_type": "commit", "content": {"repository": "a/b"}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_rejects_content_not_matching_type_schema(self):
        report = self._create_report()
        artefact = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note="before"),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        response = self.client.patch(
            f"{self._list_url(str(report.id))}{artefact.id}/",
            data=json.dumps({"content": {"note": "   "}}),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "before", "author": None}


_COMMIT_CONTENT = {
    "repository": "PostHog/posthog",
    "branch": "posthog-code/fix-foo",
    "commit_sha": "abc123f",
    "message": "fix: foo",
}


class TestSignalReportCommitDiff(APIBaseTest):
    """The commit artefact `diff` action — status-code contract the UI relies on."""

    def _diff_url(self, report_id: str, artefact_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/{artefact_id}/diff/"

    def _create_report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_commit_artefact(self, report: SignalReport, content: dict | list | None = None) -> SignalReportArtefact:
        return SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.COMMIT,
            content=json.dumps(content if content is not None else _COMMIT_CONTENT),
        )

    def test_diff_rejects_non_commit_artefact(self):
        report = self._create_report()
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": "x"}),
        )
        response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "commit artefacts" in response.json()["error"]

    @parameterized.expand(
        [
            ("missing_repository", {"branch": "b", "commit_sha": "abc123f", "message": "m"}),
            ("missing_branch", {"repository": "PostHog/posthog", "commit_sha": "abc123f", "message": "m"}),
        ]
    )
    def test_diff_rejects_incomplete_content(self, _name, content):
        report = self._create_report()
        artefact = self._create_commit_artefact(report, content)
        response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_diff_returns_404_when_no_integration_can_access_repo(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        with patch("products.signals.backend.views.GitHubIntegration.first_for_team_repository", return_value=None):
            response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def _mock_github(self, result: dict):
        github = patch("products.signals.backend.views.GitHubIntegration.first_for_team_repository").start()
        self.addCleanup(patch.stopall)
        github.return_value.get_default_branch.return_value = "master"
        github.return_value.get_diff.return_value = result
        return github

    def test_diff_success_returns_diff_and_truncated(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        self._mock_github({"success": True, "diff": "diff --git a b", "truncated": False})

        response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"diff": "diff --git a b", "truncated": False}

    def test_diff_maps_upstream_404(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        self._mock_github({"success": False, "error": "Not Found", "status_code": 404})

        response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_diff_maps_upstream_failure_to_502(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        self._mock_github({"success": False, "error": "boom", "status_code": 500})

        response = self.client.get(self._diff_url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY


class TestSignalReportReviewComments(APIBaseTest):
    """The commit artefact `review-comments` action — PR resolution + status-code contract the UI relies on."""

    def _url(self, report_id: str, artefact_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/{artefact_id}/review-comments/"

    def _create_report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _create_commit_artefact(self, report: SignalReport, content: dict | list | None = None) -> SignalReportArtefact:
        return SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.COMMIT,
            content=json.dumps(content if content is not None else _COMMIT_CONTENT),
        )

    def _mock_github(self):
        github = patch("products.signals.backend.views.GitHubIntegration.first_for_team_repository").start()
        self.addCleanup(patch.stopall)
        return github.return_value

    def test_review_comments_rejects_non_commit_artefact(self):
        report = self._create_report()
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": "x"}),
        )
        response = self.client.get(self._url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "commit artefacts" in response.json()["error"]

    @parameterized.expand(
        [
            ("missing_repository", {"branch": "b", "commit_sha": "abc123f", "message": "m"}),
            ("missing_branch", {"repository": "PostHog/posthog", "commit_sha": "abc123f", "message": "m"}),
        ]
    )
    def test_review_comments_rejects_incomplete_content(self, _name, content):
        report = self._create_report()
        artefact = self._create_commit_artefact(report, content)
        response = self.client.get(self._url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_review_comments_returns_404_when_no_integration_can_access_repo(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        with patch("products.signals.backend.views.GitHubIntegration.first_for_team_repository", return_value=None):
            response = self.client.get(self._url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_review_comments_resolves_pr_from_implementation_url(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        github = self._mock_github()
        github.get_pull_request_comments.return_value = {
            "success": True,
            "comments": [{"kind": "review", "author": "bob", "body": "lgtm", "review_state": "APPROVED"}],
        }
        with patch(
            "products.signals.backend.views.fetch_implementation_pr_urls_for_reports",
            return_value={str(report.id): "https://github.com/PostHog/posthog/pull/321"},
        ):
            response = self.client.get(self._url(str(report.id), str(artefact.id)))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["comments"][0]["author"] == "bob"
        # PR number is parsed from the implementation PR url; the branch-listing fallback is not used.
        github.get_pull_request_comments.assert_called_once_with("PostHog/posthog", 321)
        github.list_pull_requests.assert_not_called()

    def test_review_comments_resolves_pr_via_branch_when_no_url(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        github = self._mock_github()
        github.list_pull_requests.return_value = {
            "success": True,
            "pull_requests": [
                {"number": 99, "head_branch": "other-branch"},
                {"number": 55, "head_branch": _COMMIT_CONTENT["branch"]},
            ],
        }
        github.get_pull_request_comments.return_value = {"success": True, "comments": []}
        with patch("products.signals.backend.views.fetch_implementation_pr_urls_for_reports", return_value={}):
            response = self.client.get(self._url(str(report.id), str(artefact.id)))

        assert response.status_code == status.HTTP_200_OK
        github.get_pull_request_comments.assert_called_once_with("PostHog/posthog", 55)

    def test_review_comments_returns_404_when_no_pr_resolved(self):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        github = self._mock_github()
        github.list_pull_requests.return_value = {"success": True, "pull_requests": []}
        with patch("products.signals.backend.views.fetch_implementation_pr_urls_for_reports", return_value={}):
            response = self.client.get(self._url(str(report.id), str(artefact.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        github.get_pull_request_comments.assert_not_called()

    @parameterized.expand(
        [
            ("upstream_404", 404, status.HTTP_404_NOT_FOUND),
            ("upstream_500", 500, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    def test_review_comments_maps_upstream_failure(self, _name, upstream_status, expected_status):
        report = self._create_report()
        artefact = self._create_commit_artefact(report)
        github = self._mock_github()
        github.get_pull_request_comments.return_value = {"success": False, "status_code": upstream_status}
        with patch(
            "products.signals.backend.views.fetch_implementation_pr_urls_for_reports",
            return_value={str(report.id): "https://github.com/PostHog/posthog/pull/321"},
        ):
            response = self.client.get(self._url(str(report.id), str(artefact.id)))
        assert response.status_code == expected_status
