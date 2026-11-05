from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import close_old_connections
from django.utils import timezone

from parameterized import parameterized

from posthog.models import HealthIssue, Organization, OrganizationMembership, Team, User

from products.notifications.backend.facade.api import create_notification
from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.signals.backend.startup_failure import (
    ISSUE_KIND,
    ResearchStartupFailure,
    notify_research_startup_failure,
    reconcile_research_startups,
)
from products.tasks.backend.facade.contracts import AgentStartupFailure
from products.tasks.backend.models import Task, TaskRun


class TestResearchStartupFailure(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.task = Task.objects.create(
            team=self.team, title="Example research", repository="example/research", created_by=self.user
        )
        self.started_at = timezone.now()
        self.task_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status=TaskRun.Status.FAILED,
            state={"startup_started_at": self.started_at.isoformat(), "startup_runtime": "gvisor"},
        )
        self.failure = ResearchStartupFailure(
            failure=AgentStartupFailure(
                provider="claude", phase="sdk_initialization", reason="proxy_invalid", retryability="requires_action"
            ),
            task_id=self.task.id,
            run_id=self.task_run.id,
            repository="example/research",
        )
        self.report_id = str(uuid4())

    def notify(self) -> None:
        notify_research_startup_failure(self.team.id, self.report_id, self.failure)

    def test_repeated_failures_notify_only_admins_once_per_episode(self) -> None:
        member = User.objects.create(email="member@example.com")
        OrganizationMembership.objects.create(
            organization=self.organization, user=member, level=OrganizationMembership.Level.MEMBER
        )
        with patch(
            "products.signals.backend.startup_failure.create_notification", wraps=create_notification
        ) as dispatch:
            self.notify()
            self.notify()
        assert dispatch.call_args.args[0].priority == "normal"

        issue = HealthIssue.objects.get(team=self.team, kind=ISSUE_KIND)
        (event,) = stored_notifications_for_team(self.team.id)
        assert issue.status == HealthIssue.Status.ACTIVE
        assert event.resolved_user_ids == [self.user.id]
        assert event.source_url == f"/project/{self.team.id}/inbox/{self.report_id}"
        assert "proxy configuration" in event.body

    @parameterized.expand(
        [
            ("older", "claude", "gvisor", -1, False),
            ("other_provider", "codex", "gvisor", 1, False),
            ("other_runtime", "claude", "vm", 1, False),
            ("matching", "claude", "gvisor", 1, True),
        ]
    )
    def test_only_newer_matching_startup_resolves(
        self, name: str, provider: str, runtime: str, offset: int, resolves: bool
    ) -> None:
        self.notify()
        TaskRun.objects.create(
            team=self.team,
            task=self.task,
            state={
                "agent_startup_success": {
                    "started_at": (self.started_at + timedelta(seconds=offset)).isoformat(),
                    "completed_at": (self.started_at + timedelta(seconds=offset + 1)).isoformat(),
                    "repository": "example/research",
                    "provider": provider,
                    "runtime": runtime,
                }
            },
        )
        reconcile_research_startups(self.team.id, "example/research")
        issue = HealthIssue.objects.get(team=self.team, kind=ISSUE_KIND)
        assert (issue.status == HealthIssue.Status.RESOLVED) is resolves
        self.notify()
        assert len(stored_notifications_for_team(self.team.id)) == 1

        if resolves:
            self.task_run.state["startup_started_at"] = (self.started_at + timedelta(seconds=3)).isoformat()
            self.task_run.save(update_fields=["state"])
            self.notify()
            assert HealthIssue.objects.filter(team=self.team, status=HealthIssue.Status.ACTIVE).count() == 1
            assert len(stored_notifications_for_team(self.team.id)) == 2

    def test_success_observed_before_delayed_failure_suppresses_notice(self) -> None:
        TaskRun.objects.create(
            team=self.team,
            task=self.task,
            state={
                "agent_startup_success": {
                    "started_at": (self.started_at + timedelta(seconds=1)).isoformat(),
                    "completed_at": (self.started_at + timedelta(seconds=2)).isoformat(),
                    "repository": "example/research",
                    "provider": "claude",
                    "runtime": "gvisor",
                }
            },
        )
        self.notify()
        assert not HealthIssue.objects.filter(team=self.team, kind=ISSUE_KIND).exists()
        assert not stored_notifications_for_team(self.team.id)

    def test_delivery_failure_retains_issue_and_can_be_retried(self) -> None:
        with patch(
            "products.signals.backend.startup_failure.create_notification", side_effect=RuntimeError("unavailable")
        ):
            with pytest.raises(RuntimeError, match="unavailable"):
                self.notify()
        assert HealthIssue.objects.filter(team=self.team, status=HealthIssue.Status.ACTIVE).count() == 1
        assert not stored_notifications_for_team(self.team.id)
        self.notify()
        assert len(stored_notifications_for_team(self.team.id)) == 1

    def test_recovery_between_failures_starts_a_new_episode_without_reconciliation(self) -> None:
        self.notify()
        previous = HealthIssue.objects.get(team=self.team, kind=ISSUE_KIND)
        self.task_run.state.update(
            agent_startup_success={
                "repository": self.task.repository,
                "provider": "claude",
                "runtime": "gvisor",
                "started_at": (self.started_at + timedelta(seconds=1)).isoformat(),
                "completed_at": (self.started_at + timedelta(seconds=2)).isoformat(),
            },
            agent_startup_attempt={
                "repository": self.task.repository,
                "provider": "claude",
                "runtime": "gvisor",
                "started_at": (self.started_at + timedelta(seconds=3)).isoformat(),
            },
        )
        self.task_run.save(update_fields=["state"])
        self.notify()
        previous.refresh_from_db()
        assert previous.status == HealthIssue.Status.RESOLVED
        assert (
            HealthIssue.objects.filter(team=self.team, kind=ISSUE_KIND, status=HealthIssue.Status.ACTIVE).count() == 1
        )
        assert len(stored_notifications_for_team(self.team.id)) == 2

    def test_agent_reported_success_is_not_recovery_evidence(self) -> None:
        self.notify()
        TaskRun.objects.create(
            team=self.team,
            task=self.task,
            state={
                "startup_started_at": (self.started_at + timedelta(days=1)).isoformat(),
                "startup_completed_at": (self.started_at + timedelta(days=2)).isoformat(),
                "startup_provider": "claude",
                "startup_runtime": "gvisor",
            },
        )
        reconcile_research_startups(self.team.id, "example/research")
        assert HealthIssue.objects.get(team=self.team, kind=ISSUE_KIND).status == HealthIssue.Status.ACTIVE

    def test_other_team_cannot_create_an_issue_from_this_run(self) -> None:
        notify_research_startup_failure(self.team.id + 10000, self.report_id, self.failure)
        assert not HealthIssue.objects.filter(kind=ISSUE_KIND).exists()

    def test_unknown_failure_does_not_claim_a_configuration_cause(self) -> None:
        self.failure = replace(
            self.failure,
            failure=AgentStartupFailure(
                provider="claude",
                phase="sdk_initialization",
                reason=None,
                retryability="unknown",
            ),
        )
        self.notify()
        (event,) = stored_notifications_for_team(self.team.id)
        assert "did not report a confirmed cause" in event.body
        assert "automatically" not in event.body


@pytest.mark.django_db(transaction=True)
def test_concurrent_failures_share_one_issue_and_notification() -> None:
    organization = Organization.objects.create(name="Example concurrency")
    team = Team.objects.create(organization=organization)
    user = User.objects.create(email="concurrency@example.com")
    OrganizationMembership.objects.create(
        organization=organization, user=user, level=OrganizationMembership.Level.ADMIN
    )
    task = Task.objects.create(team=team, created_by=user, repository="example/concurrent", title="Example research")
    run = TaskRun.objects.create(
        team=team, task=task, state={"startup_started_at": timezone.now().isoformat(), "startup_runtime": "gvisor"}
    )
    failure = ResearchStartupFailure(
        failure=AgentStartupFailure(provider="claude", phase="sdk_initialization", reason=None, retryability="unknown"),
        task_id=task.id,
        run_id=run.id,
        repository="example/concurrent",
    )
    barrier = Barrier(2)

    def notify() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            notify_research_startup_failure(team.id, str(uuid4()), failure)
        finally:
            close_old_connections()

    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch("products.notifications.backend.logic._publish_to_kafka"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        futures = [pool.submit(notify) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert HealthIssue.objects.filter(team=team, kind=ISSUE_KIND).count() == 1
    assert len(stored_notifications_for_team(team.id)) == 1
