import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.auth import MCP_USER_AGENT_MARKER
from posthog.models import User
from posthog.utils import absolute_uri

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PullRequestLink
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
)
from products.signals.backend.report_assignments import create_claim
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
class TestInboxDigest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "test-password")

    def _report(
        self,
        title: str,
        *,
        priority: str | None = None,
        visible_ago: timedelta | None = None,
        names: User | None = None,
        claimed_by: ArtefactAttribution | None = None,
        **fields: Any,
    ) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            title=title,
            summary=f"{title} for EU cards.\n\n## Evidence\nThe full research.",
            first_visible_at=NOW - visible_ago if visible_ago is not None else None,
            **{
                "status": SignalReport.Status.READY,
                "latest_actionability": "immediately_actionable",
                "latest_already_addressed": False,
                **fields,
            },
        )
        if priority is not None:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=json.dumps({"priority": priority}),
            )
        if names is not None:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps([{"user_uuid": str(names.uuid)}]),
            )
        if claimed_by is not None:
            create_claim(report, claimed_by)
        return report

    def _link_pr(
        self,
        report: SignalReport,
        number: int,
        *,
        state: str,
        linked_ago: timedelta,
        merged_ago: timedelta | None = None,
    ) -> SignalReportPullRequest:
        pr = SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team,
            repository="example/app",
            number=number,
            url=f"https://github.com/example/app/pull/{number}",
            state=state,
            merged_at=NOW - merged_ago if merged_ago is not None else None,
        )
        SignalReportPullRequest.objects.for_team(self.team.id).filter(id=pr.id).update(created_at=NOW - linked_ago)
        link = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PullRequestLink(url=pr.url),
            attribution=ArtefactAttribution.system(),
        )
        link.pull_request = pr
        link.save(update_fields=["pull_request"])
        return pr

    def _digest(self, **query: str) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/inbox_digest/", query)
        assert response.status_code == 200, response.content
        return response.json()

    @parameterized.expand(
        [
            ("default_one_day", None, NOW - timedelta(days=1), ["reviewing", "waiting"]),
            ("explicit", NOW - timedelta(days=5), NOW - timedelta(days=5), ["reviewing", "claimed", "waiting"]),
            (
                "clamped_to_30_days",
                NOW - timedelta(days=60),
                NOW - timedelta(days=30),
                ["reviewing", "claimed", "waiting"],
            ),
        ]
    )
    def test_needs_you_is_current_state_and_new_for_you_counts_from_since(
        self, _name: str, since: datetime | None, expected_since: datetime, expected_new: list[str]
    ) -> None:
        me = ArtefactAttribution.from_user(self.user.id)
        reports = {
            "waiting": self._report(
                "Waits on input",
                priority="P2",
                visible_ago=timedelta(hours=2),
                names=self.user,
                status=SignalReport.Status.PENDING_INPUT,
            ),
            "claimed": self._report("Claimed by me", priority="P1", visible_ago=timedelta(days=3), claimed_by=me),
            "reviewing": self._report("Names me", priority="P0", visible_ago=timedelta(hours=1), names=self.user),
            "older": self._report("Older review", priority="P3", visible_ago=timedelta(days=40), names=self.user),
        }
        self._report(
            "Claimed by a teammate",
            priority="P0",
            visible_ago=timedelta(hours=1),
            claimed_by=ArtefactAttribution.from_user(self.teammate.id),
        )
        self._report("Names a teammate", priority="P0", visible_ago=timedelta(hours=1), names=self.teammate)
        self._link_pr(reports["claimed"], 7, state="open", linked_ago=timedelta(hours=1))

        digest = self._digest(**({"since": since.isoformat()} if since else {}))

        names_by_id = {str(report.id): name for name, report in reports.items()}
        assert digest["since"] == expected_since.isoformat().replace("+00:00", "Z")
        assert digest["needs_you"]["count"] == 4
        assert [(names_by_id[row["id"]], row["relation"]) for row in digest["needs_you"]["reports"]] == [
            ("reviewing", "suggested_reviewer"),
            ("claimed", "claimed"),
            ("waiting", "waiting_for_you"),
        ]
        assert digest["new_for_you"]["count"] == len(expected_new)
        assert [names_by_id[row["id"]] for row in digest["new_for_you"]["reports"]] == expected_new
        claimed_id = str(reports["claimed"].id)
        assert next(row for row in digest["needs_you"]["reports"] if row["id"] == claimed_id) == {
            "id": claimed_id,
            "title": "Claimed by me",
            "priority": "P1",
            "status": "ready",
            "relation": "claimed",
            "summary_lead": "Claimed by me for EU cards.",
            "implementation_pr_url": "https://github.com/example/app/pull/7",
            "implementation_pr_state": "open",
            "url": absolute_uri(f"/project/{self.team.id}/inbox/reports/{claimed_id}"),
        }

    @parameterized.expand([("monitoring_on", True), ("monitoring_off", False)])
    def test_outcomes_count_only_the_persons_reports_from_since(self, _name: str, monitoring: bool) -> None:
        named = self._report("Names me", names=self.user)
        agent_claimed = self._report(
            "Claimed by my agent", claimed_by=ArtefactAttribution.from_agent(self.user.id, "Claude Code")
        )
        teammates = self._report("Names a teammate", names=self.teammate)
        self._link_pr(named, 1, state="merged", linked_ago=timedelta(hours=2), merged_ago=timedelta(hours=1))
        self._link_pr(agent_claimed, 2, state="open", linked_ago=timedelta(hours=3))
        self._link_pr(named, 3, state="merged", linked_ago=timedelta(days=5), merged_ago=timedelta(days=3))
        self._link_pr(teammates, 4, state="merged", linked_ago=timedelta(hours=1), merged_ago=timedelta(minutes=30))

        def ended_monitoring(title: str, status: str, ended_ago: timedelta, **owner: Any) -> None:
            self._report(
                title,
                status=status,
                monitoring_started_at=NOW - timedelta(days=6),
                monitoring_ended_at=NOW - ended_ago,
                **owner,
            )

        ended_monitoring("Resolved by me", SignalReport.Status.RESOLVED, timedelta(hours=2), names=self.user)
        ended_monitoring(
            "Closed",
            SignalReport.Status.CLOSED,
            timedelta(hours=3),
            claimed_by=ArtefactAttribution.from_user(self.user.id),
        )
        ended_monitoring("Ended before since", SignalReport.Status.RESOLVED, timedelta(days=3), names=self.user)
        ended_monitoring("A teammate's", SignalReport.Status.RESOLVED, timedelta(hours=1), names=self.teammate)

        with patch(
            "products.signals.backend.inbox_digest.organization_report_monitoring_enabled", return_value=monitoring
        ):
            outcomes = self._digest()["outcomes"]

        assert outcomes == {
            "pull_requests_opened": 2,
            "pull_requests_merged": 1,
            "monitoring_periods_ended": [
                {"outcome": "resolved_manually", "count": 1},
                {"outcome": "closed", "count": 1},
            ]
            if monitoring
            else None,
        }

    @parameterized.expand([("live_filters", False), ("cached_columns", True)])
    def test_project_count_matches_the_actionable_unclaimed_list_count(self, _name: str, cached: bool) -> None:
        self._report("Free to take")
        self._report("Also free to take")
        self._report("Claimed", claimed_by=ArtefactAttribution.from_user(self.teammate.id))
        with_pr = self._report("Has a pull request")
        with self.captureOnCommitCallbacks(execute=True):
            SignalReportAssignment.all_teams.create(
                team=self.team, report=with_pr, pr_url="https://github.com/example/app/pull/9", pr_state="open"
            )
        self._report("Already addressed", latest_already_addressed=True)
        self._report("Not actionable", latest_actionability="not_actionable")
        self._report("Needs input", status=SignalReport.Status.PENDING_INPUT)

        with (
            patch("products.signals.backend.views.organization_inbox_cached_filters_enabled", return_value=cached),
            patch(
                "products.signals.backend.inbox_digest.organization_inbox_cached_filters_enabled", return_value=cached
            ),
        ):
            digest_count = self._digest()["project"]["actionable_unclaimed_count"]
            list_response = self.client.get(
                f"/api/projects/{self.team.id}/signals/reports/",
                {"view": "actionable", "unclaimed": "true", "count_only": "true"},
            )

        assert list_response.status_code == 200, list_response.content
        assert digest_count == list_response.json()["count"] == 2

    def test_refuses_service_authentication(self) -> None:
        with patch("products.signals.backend.presentation.inbox_digest.is_service_auth", return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/signals/inbox_digest/")

        assert response.status_code == 403

    @parameterized.expand([("private_scout_trial", True, 403), ("scout_sandbox", False, 200)])
    def test_refuses_a_private_scout_trial_token(self, _name: str, private: bool, expected_status: int) -> None:
        run = _make_run(
            self.team, metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}} if private else {}
        )
        _authenticate_as_scout(
            self,
            scopes="signals_scout_experiment" if private else "signals_scout",
            sandbox_task_id=run.task_run.task_id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/signals/inbox_digest/")

        assert response.status_code == expected_status, response.content

    @parameterized.expand([("api", "python-requests/2.32", ""), ("mcp", MCP_USER_AGENT_MARKER, "?link_source=mcp")])
    def test_report_links_name_mcp_only_for_mcp_requests(self, _name: str, user_agent: str, suffix: str) -> None:
        report = self._report("Names me", names=self.user, visible_ago=timedelta(hours=1))
        api_key = self.create_personal_api_key_with_scopes(["inbox:read"])
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/signals/inbox_digest/",
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
            HTTP_USER_AGENT=user_agent,
        )

        assert response.status_code == 200, response.content
        assert [row["url"] for row in response.json()["needs_you"]["reports"]] == [
            absolute_uri(f"/project/{self.team.id}/inbox/reports/{report.id}{suffix}")
        ]

    def test_query_count_does_not_grow_with_the_number_of_reports(self) -> None:
        def add_reports(start: int, count: int) -> None:
            for number in range(start, start + count):
                report = self._report(
                    f"Report {number}", priority="P1", visible_ago=timedelta(hours=1), names=self.user
                )
                self._link_pr(
                    report, number, state="merged", linked_ago=timedelta(hours=2), merged_ago=timedelta(hours=1)
                )

        def digest_queries() -> int:
            with CaptureQueriesContext(connection) as queries:
                self._digest()
            return len(queries)

        add_reports(1, 1)
        self._digest()
        with_one = digest_queries()
        add_reports(2, 4)

        assert digest_queries() == with_one
