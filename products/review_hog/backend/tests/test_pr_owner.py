import json

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.review_hog.backend.pr_owner import PullRequestOwner, PullRequestOwnerResolver, pick_pr_owner
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.tasks.backend.models import Task, TaskRun

_HEAD_BRANCH = "posthog-code/fix-the-thing"


class TestPickPullRequestOwner(SimpleTestCase):
    @parameterized.expand(
        [
            ("mapped_author", 1, False, None, PullRequestOwner(user_id=1, source="author")),
            ("mapped_author_wins_over_the_inbox", 1, True, 2, PullRequestOwner(user_id=1, source="author")),
            ("self_driving_pr", None, True, 2, PullRequestOwner(user_id=2, source="inbox_reviewer")),
            ("self_driving_pr_without_reviewer", None, True, None, PullRequestOwner(user_id=None, source="none")),
            # Another bot can claim an Inbox branch name; only the PostHog app's pull requests link to a report.
            ("other_author_on_an_inbox_branch", None, False, 2, PullRequestOwner(user_id=None, source="none")),
        ]
    )
    def test_owner_rule(
        self,
        _name: str,
        author_user_id: int | None,
        authored_by_posthog_app: bool,
        inbox_reviewer_id: int | None,
        expected: PullRequestOwner,
    ) -> None:
        owner = pick_pr_owner(
            author_user_id=author_user_id,
            authored_by_posthog_app=authored_by_posthog_app,
            inbox_reviewer_id=inbox_reviewer_id,
        )
        assert owner == expected


class TestPullRequestOwnerResolver(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="gh-1", extra_data={"login": "OctoCat"})
        self.reviewer = User.objects.create(email="alice@posthog.com")
        OrganizationMembership.objects.create(user=self.reviewer, organization=self.organization)
        UserSocialAuth.objects.create(user=self.reviewer, provider="github", uid="gh-2", extra_data={"login": "alice"})
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "alice"}]),
        )
        task = Task.objects.create(
            team=self.team,
            title="Implement the fix",
            description="from a signal report",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            repository="PostHog/posthog",
            signal_report=report,
            internal=True,
        )
        TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"ai_stage": "implementation", "self_driving_head_branch": _HEAD_BRANCH},
        )

    def _resolve(self, author_login: str, head_branch: str = _HEAD_BRANCH) -> PullRequestOwner:
        with override_instance_config("GITHUB_APP_SLUG", "posthog-app"):
            return PullRequestOwnerResolver.resolve(
                self.team.id, repository="PostHog/posthog", author_login=author_login, head_branch=head_branch
            )

    def test_an_active_author_owns_the_pull_request(self) -> None:
        assert self._resolve("octocat") == PullRequestOwner(user_id=self.user.id, source="author")

    def test_an_inactive_author_owns_nothing(self) -> None:
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        assert self._resolve("octocat") == PullRequestOwner(user_id=None, source="none")

    @parameterized.expand(
        [
            ("posthog_app_on_the_inbox_branch", "posthog-app[bot]", _HEAD_BRANCH, "inbox_reviewer"),
            ("posthog_app_on_another_branch", "posthog-app[bot]", "some-other-branch", "none"),
            ("another_bot_on_the_inbox_branch", "renovate[bot]", _HEAD_BRANCH, "none"),
        ]
    )
    def test_a_self_driving_pull_request_belongs_to_the_inbox_reviewer(
        self, _name: str, author_login: str, head_branch: str, source: str
    ) -> None:
        owner = self._resolve(author_login, head_branch)
        assert owner.source == source
        assert owner.user_id == (self.reviewer.id if source == "inbox_reviewer" else None)
