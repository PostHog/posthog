import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User

from products.signals.backend.implementation_pr import ImplementationPr
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.personal_inbox import (
    ClaimHolder,
    PersonalActionState,
    PersonalNextActionKind,
    PersonalReason,
    ReportFacts,
    decide,
    rank_report_ids,
)
from products.signals.backend.report_assignments import create_claim

VIEWER_ID = 1
OTHER_ID = 2
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _pr(
    number: int, state: str, *, review_decision: str | None = None, author_id: int | None = None
) -> ImplementationPr:
    return ImplementationPr(
        url=f"https://github.com/example/repo/pull/{number}",
        merged=state == "merged",
        state=state,
        review_decision=review_decision,
        attached_by_user=User(id=author_id) if author_id is not None else None,
        checked_at=NOW,
    )


def _facts(
    report_id: str = "r1",
    *,
    status: str = SignalReport.Status.READY,
    actionability: str | None = "immediately_actionable",
    already_addressed: bool | None = False,
    priority: str | None = "P2",
    changed_at: datetime = NOW,
    names_viewer: bool = True,
    claim_holder: ClaimHolder | None = None,
    pull_requests: tuple[ImplementationPr, ...] = (),
) -> ReportFacts:
    return ReportFacts(
        report_id=report_id,
        status=status,
        actionability=actionability,
        already_addressed=already_addressed,
        priority=priority,
        updated_at=NOW,
        changed_at=changed_at,
        names_viewer=names_viewer,
        claim_holder=claim_holder,
        pull_requests=pull_requests,
        viewer_id=VIEWER_ID,
    )


class TestPersonalInboxDecision(SimpleTestCase):
    @parameterized.expand(
        [
            ("new_finding", _facts(), PersonalActionState.ACTION_AVAILABLE, PersonalNextActionKind.REVIEW_FINDING),
            (
                "question_waiting_on_viewer",
                _facts(status=SignalReport.Status.PENDING_INPUT, actionability="requires_human_input"),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.ANSWER_QUESTION,
            ),
            (
                "open_pr_needs_review",
                _facts(pull_requests=(_pr(1, "open", author_id=OTHER_ID),)),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.REVIEW_PR,
            ),
            (
                "one_merged_layer_does_not_finish_the_stack",
                _facts(pull_requests=(_pr(1, "merged"), _pr(2, "open"))),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.REVIEW_PR,
            ),
            (
                "own_pr_is_not_a_review",
                _facts(pull_requests=(_pr(1, "open", author_id=VIEWER_ID),)),
                PersonalActionState.WAITING,
                None,
            ),
            (
                "approved_pr_waits_on_its_author",
                _facts(pull_requests=(_pr(1, "open", review_decision="approved"),)),
                PersonalActionState.WAITING,
                None,
            ),
            ("draft_pr", _facts(pull_requests=(_pr(1, "draft"),)), PersonalActionState.WAITING, None),
            (
                "viewer_owns_the_open_pr",
                _facts(claim_holder=ClaimHolder.VIEWER, pull_requests=(_pr(1, "open"),)),
                PersonalActionState.WAITING,
                None,
            ),
            (
                "unverified_pr_state",
                _facts(pull_requests=(_pr(1, "unknown"),)),
                PersonalActionState.UNKNOWN,
                PersonalNextActionKind.CHECK_PR,
            ),
            ("merged_but_report_open", _facts(pull_requests=(_pr(1, "merged"),)), PersonalActionState.WAITING, None),
            (
                "closed_pr_needs_a_new_decision",
                _facts(pull_requests=(_pr(1, "closed"),)),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.REVIEW_FINDING,
            ),
            ("research_running", _facts(status=SignalReport.Status.IN_PROGRESS), PersonalActionState.WAITING, None),
            ("viewer_agent_working", _facts(claim_holder=ClaimHolder.VIEWER_TASK), PersonalActionState.WAITING, None),
            ("someone_else_owns_it", _facts(claim_holder=ClaimHolder.OTHER), PersonalActionState.WAITING, None),
            (
                "viewer_owns_it",
                _facts(claim_holder=ClaimHolder.VIEWER),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.CONTINUE_WORK,
            ),
            (
                "viewer_owned_work_failed",
                _facts(status=SignalReport.Status.FAILED, names_viewer=False, claim_holder=ClaimHolder.VIEWER),
                PersonalActionState.ACTION_AVAILABLE,
                PersonalNextActionKind.RESOLVE_BLOCKER,
            ),
            ("already_addressed", _facts(already_addressed=True), PersonalActionState.UNKNOWN, None),
            ("resolved", _facts(status=SignalReport.Status.RESOLVED), PersonalActionState.CLOSED, None),
        ]
    )
    def test_action_state(
        self,
        _name: str,
        facts: ReportFacts,
        expected_state: PersonalActionState,
        expected_action: PersonalNextActionKind | None,
    ) -> None:
        decision = decide(facts)

        assert decision.action_state == expected_state
        assert (decision.next_action.kind if decision.next_action else None) == expected_action

    def test_reasons_follow_reviewer_and_claim(self) -> None:
        assert decide(_facts(claim_holder=ClaimHolder.VIEWER_TASK)).reasons == (
            PersonalReason.SUGGESTED_REVIEWER,
            PersonalReason.CLAIMED,
        )
        assert decide(_facts(names_viewer=False, claim_holder=ClaimHolder.OTHER)).reasons == ()
        assert decide(_facts(actionability="not_actionable")).reasons == ()

    def test_review_action_points_at_the_pr_that_needs_review(self) -> None:
        decision = decide(_facts(pull_requests=(_pr(1, "draft"), _pr(2, "open"))))

        assert decision.next_action is not None
        assert decision.next_action.pull_request_url == "https://github.com/example/repo/pull/2"
        assert decision.observed_at == NOW

    def test_order(self) -> None:
        decisions = [
            decide(_facts("recent_p3", priority="P3", changed_at=NOW)),
            decide(
                _facts("owned_p2", priority="P2", claim_holder=ClaimHolder.VIEWER, changed_at=NOW - timedelta(days=9))
            ),
            decide(_facts("new_p1", priority="P1", changed_at=NOW - timedelta(days=10))),
            decide(_facts("waiting_p0", priority="P0", pull_requests=(_pr(1, "draft"),))),
            decide(_facts("unknown_p1", priority="P1", pull_requests=(_pr(2, "unknown"),))),
            decide(_facts("urgent_p0", priority="P0", changed_at=NOW - timedelta(days=30))),
            decide(_facts("reviewer_p2", priority="P2", changed_at=NOW - timedelta(days=9))),
            decide(_facts("reviewer_p2_same_time", priority="P2", changed_at=NOW - timedelta(days=9))),
        ]

        assert rank_report_ids(decisions) == [
            "urgent_p0",
            "new_p1",
            "owned_p2",
            "reviewer_p2",
            "reviewer_p2_same_time",
            "recent_p3",
            "unknown_p1",
            "waiting_p0",
        ]


@patch("products.signals.backend.views.personal_inbox_enabled", return_value=True)
class TestPersonalInboxListAPI(APIBaseTest):
    def _list(self, **query) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?{urlencode(query)}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _report(self, title: str, *, team: Team | None = None, priority: str = "P2", **kwargs) -> SignalReport:
        report = SignalReport.objects.create(
            team=team or self.team,
            title=title,
            status=kwargs.pop("status", SignalReport.Status.READY),
            latest_actionability="immediately_actionable",
            latest_already_addressed=False,
            **kwargs,
        )
        SignalReportArtefact.objects.create(
            team=report.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority}),
        )
        return report

    def _name_reviewer(self, report: SignalReport, user: User) -> None:
        SignalReportArtefact.objects.create(
            team=report.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(user.uuid)}]),
        )

    def _task_claim(self, report: SignalReport, created_by: User) -> None:
        task = apps.get_model("tasks", "Task").objects.create(
            team=report.team, title="Agent work", description="Work", created_by=created_by
        )
        create_claim(report, ArtefactAttribution.from_task(str(task.id)))

    def test_for_me_selects_only_the_viewers_reports(self, _flag) -> None:
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_org_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))

        reviewed = self._report("Reviewer")
        self._name_reviewer(reviewed, self.user)
        claimed = self._report("Claimed")
        create_claim(claimed, ArtefactAttribution.from_user(self.user.id))
        agent_claimed = self._report("Viewer's agent")
        self._task_claim(agent_claimed, self.user)

        teammate_review = self._report("Teammate reviewer")
        self._name_reviewer(teammate_review, teammate)
        self._task_claim(self._report("Teammate's agent"), teammate)
        self._report("Nobody's")
        for team in (other_team, other_org_team):
            self._name_reviewer(self._report("Other project", team=team), self.user)
        for closed_status in (
            SignalReport.Status.RESOLVED,
            SignalReport.Status.SUPPRESSED,
            SignalReport.Status.POTENTIAL,
        ):
            self._name_reviewer(self._report(f"Closed {closed_status}", status=closed_status), self.user)

        body = self._list(scope="for_me")
        count = self._list(scope="for_me", count_only="true")["count"]

        assert {row["title"] for row in body["results"]} == {"Reviewer", "Claimed", "Viewer's agent"}
        assert body["count"] == count == 3
        reasons = {row["title"]: row["personal_inbox"]["reasons"] for row in body["results"]}
        assert reasons == {
            "Reviewer": ["suggested_reviewer"],
            "Claimed": ["claimed"],
            "Viewer's agent": ["claimed"],
        }
        assert {row["title"] for row in self._list(scope="for_me", view="resolved")["results"]} == {"Closed resolved"}

    def test_relevance_ranks_before_pagination(self, _flag) -> None:
        low = self._report("Low", priority="P4")
        urgent = self._report("Urgent", priority="P0")
        waiting = self._report("Waiting", priority="P1", status=SignalReport.Status.IN_PROGRESS)
        high = self._report("High", priority="P1")
        for report in (low, urgent, waiting, high):
            self._name_reviewer(report, self.user)

        first = self._list(scope="for_me", sort="relevance", limit=2)
        second = self._list(scope="for_me", sort="relevance", limit=2, offset=2)

        assert [row["title"] for row in first["results"] + second["results"]] == ["Urgent", "High", "Low", "Waiting"]
        rows = first["results"] + second["results"]
        assert sorted(rows, key=lambda row: row["personal_inbox"]["relevance_key"]) == rows
        assert first["count"] == 4
        row = first["results"][0]["personal_inbox"]
        assert row["action_state"] == "action_available"
        assert row["next_action"] == {"kind": "review_finding", "pull_request_url": None}
        assert row["policy_version"] == "personal-inbox-v1"

    @parameterized.expand(
        [
            ("bare_mcp_call", {}, {"HTTP_X_POSTHOG_CLIENT": "mcp"}, {"Mine"}),
            (
                "mcp_search_keeps_project_scope",
                {"search": "report"},
                {"HTTP_X_POSTHOG_CLIENT": "mcp"},
                {"Mine", "Theirs"},
            ),
            (
                "task_agent_keeps_project_scope",
                {},
                {"HTTP_X_POSTHOG_CLIENT": "mcp", "HTTP_X_POSTHOG_TASK_ID": "00000000-0000-4000-8000-000000000001"},
                {"Mine", "Theirs"},
            ),
            ("web_call_keeps_project_scope", {}, {}, {"Mine", "Theirs"}),
        ]
    )
    def test_bare_mcp_list_defaults_to_the_personal_inbox(
        self, _flag, _name: str, query: dict, headers: dict, expected: set[str]
    ) -> None:
        self._name_reviewer(self._report("Mine report"), self.user)
        self._report("Theirs report")

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?{urlencode(query)}", **headers)

        assert response.status_code == status.HTTP_200_OK
        assert {row["title"].removesuffix(" report") for row in response.json()["results"]} == expected

    def test_relevance_requires_the_personal_scope(self, _flag) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?sort=relevance")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_flag_off_keeps_the_reviewer_only_selection(self, flag) -> None:
        flag.return_value = False
        claimed = self._report("Claimed")
        create_claim(claimed, ArtefactAttribution.from_user(self.user.id))
        reviewed = self._report("Reviewer")
        self._name_reviewer(reviewed, self.user)

        body = self._list(scope="for_me")

        assert [row["title"] for row in body["results"]] == ["Reviewer"]
        assert body["results"][0]["personal_inbox"] is None
