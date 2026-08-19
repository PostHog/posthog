import json
from typing import ClassVar

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status as http_status
from rest_framework.test import APIClient

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.models import Channel, Task, TaskPin, TaskRun, TaskThreadMessage, TaskThreadMessageMention


class TestTaskListFilterMatrix(TestCase):
    """The task list's filters against one seeded task matrix, each with the
    exact wire params the desktop feed query language sends. Every filter is
    exercised alone and in the combinations the query language produces, and
    every assertion is an exact id set — a filter that silently stops
    filtering (the bug class this guards) fails loudly here."""

    organization: ClassVar[Organization]
    team: ClassVar[Team]
    me: ClassVar[User]
    peter: ClassVar[User]
    adam: ClassVar[User]
    tasks: ClassVar[dict[str, Task]]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Matrix Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Matrix Team")
        cls.me = User.objects.create_user(email="me@example.com", first_name="Me", password="password")
        cls.peter = User.objects.create_user(email="peter@example.com", first_name="Peter", password="password")
        cls.adam = User.objects.create_user(email="adam@example.com", first_name="Adam", password="password")
        for user in (cls.me, cls.peter, cls.adam):
            cls.organization.members.add(user)

        channel = Channel.objects.unscoped().create(team=cls.team, name="mobile", created_by=cls.me)

        def task(
            key: str,
            *,
            created_by: User,
            title: str,
            origin: str = Task.OriginProduct.USER_CREATED,
            repository: str = "posthog/posthog",
            archived: bool = False,
            in_channel: bool = False,
            run_status: str | None = None,
            output: dict | None = None,
        ) -> Task:
            t = Task.objects.create(
                team=cls.team,
                created_by=created_by,
                title=title,
                description=f"{key} description",
                origin_product=origin,
                repository=repository,
                archived=archived,
                channel=channel if in_channel else None,
            )
            if run_status is not None:
                TaskRun.objects.create(task=t, team=cls.team, status=run_status, output=output)
            return t

        def comment(task: Task, author: User, *, mentions: User | None = None, event: str = "") -> None:
            message = TaskThreadMessage.objects.for_team(cls.team.id).create(
                team=cls.team,
                task=task,
                author=author,
                author_kind=TaskThreadMessage.AuthorKind.AGENT if event else TaskThreadMessage.AuthorKind.HUMAN,
                event=event,
                content="seeded",
            )
            if mentions is not None:
                TaskThreadMessageMention.objects.for_team(cls.team.id).create(
                    team=cls.team, message=message, task=task, mentioned_user=mentions
                )

        cls.tasks = {
            # Peter's, mentions me, failed run with an open PR and red CI.
            "peter_mention_me": task(
                "peter_mention_me",
                created_by=cls.peter,
                title="Fix billing address validation",
                run_status=TaskRun.Status.FAILED,
                output={
                    "pr_url": "https://github.com/posthog/posthog/pull/1",
                    "pr_state": "open",
                    "ci_status": "failing",
                },
            ),
            # Peter's, no thread at all, merged PR (modern pr_state).
            "peter_plain": task(
                "peter_plain",
                created_by=cls.peter,
                title="Add billing period picker",
                run_status=TaskRun.Status.COMPLETED,
                output={"pr_url": "https://github.com/posthog/posthog/pull/2", "pr_state": "merged"},
            ),
            # Peter's from Slack, mentions me — origin must split this from
            # peter_mention_me.
            "peter_slack_mention_me": task(
                "peter_slack_mention_me",
                created_by=cls.peter,
                title="Slack-reported crash",
                origin=Task.OriginProduct.SLACK,
                run_status=TaskRun.Status.IN_PROGRESS,
            ),
            # Adam's, mentions Peter (not me).
            "adam_mention_peter": task(
                "adam_mention_peter",
                created_by=cls.adam,
                title="Push notification opt-in",
                run_status=TaskRun.Status.IN_PROGRESS,
            ),
            # Mine, Peter commented (no mention), green CI.
            "mine_peter_commented": task(
                "mine_peter_commented",
                created_by=cls.me,
                title="Skeleton loading for feeds",
                run_status=TaskRun.Status.IN_PROGRESS,
                output={
                    "pr_url": "https://github.com/posthog/posthog/pull/3",
                    "pr_state": "draft",
                    "ci_status": "passing",
                },
            ),
            # Mine, archived.
            "mine_archived": task("mine_archived", created_by=cls.me, title="Old spike", archived=True),
            # A scout's, queued, in the channel, other repo.
            "scout_in_channel": task(
                "scout_in_channel",
                created_by=cls.adam,
                title="Weekly anomaly sweep",
                origin=Task.OriginProduct.SIGNALS_SCOUT,
                repository="posthog/posthog.com",
                in_channel=True,
                run_status=TaskRun.Status.QUEUED,
            ),
            # Peter's, I commented; Peter pinned it (not me).
            "peter_i_commented": task(
                "peter_i_commented",
                created_by=cls.peter,
                title="Remove artifacts tab",
                run_status=TaskRun.Status.COMPLETED,
                # Legacy merged run: pr_merged flag only, no pr_state.
                output={"pr_url": "https://github.com/posthog/posthog/pull/4", "pr_merged": True},
            ),
            # Adam's, pinned by me.
            "adam_pinned_by_me": task(
                "adam_pinned_by_me",
                created_by=cls.adam,
                title="Growth funnel dashboard",
                run_status=TaskRun.Status.CANCELLED,
            ),
            # Peter's, a legacy turn_complete agent row mentioning me — the
            # mentions filter must not count it.
            "peter_legacy_mention": task(
                "peter_legacy_mention",
                created_by=cls.peter,
                title="Dark mode for settings",
                run_status=TaskRun.Status.COMPLETED,
            ),
        }

        comment(cls.tasks["peter_mention_me"], cls.peter, mentions=cls.me)
        comment(cls.tasks["peter_slack_mention_me"], cls.peter, mentions=cls.me)
        comment(cls.tasks["adam_mention_peter"], cls.adam, mentions=cls.peter)
        comment(cls.tasks["mine_peter_commented"], cls.peter)
        comment(cls.tasks["peter_i_commented"], cls.me)
        comment(cls.tasks["peter_legacy_mention"], cls.peter, mentions=cls.me, event="turn_complete")
        TaskPin.objects.create(user=cls.peter, task=cls.tasks["peter_i_commented"])
        TaskPin.objects.create(user=cls.me, task=cls.tasks["adam_pinned_by_me"])
        cls.channel = channel

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.me)

    def _list(self, **params) -> set[str]:
        response = self.client.get("/api/projects/@current/tasks/", params)
        assert response.status_code == http_status.HTTP_200_OK, json.dumps(response.json())
        return {t["id"] for t in response.json()["results"]}

    def _ids(self, *keys: str) -> set[str]:
        return {str(self.tasks[key].id) for key in keys}

    def all_except(self, *keys: str) -> set[str]:
        # The unarchived default universe.
        universe = {str(t.id) for k, t in self.tasks.items() if k != "mine_archived"}
        return universe - self._ids(*keys)

    # ------------------------------------------------------------------
    # single filters
    # ------------------------------------------------------------------

    def test_created_by(self):
        assert self._list(created_by=self.peter.id) == self._ids(
            "peter_mention_me", "peter_plain", "peter_slack_mention_me", "peter_i_commented", "peter_legacy_mention"
        )

    def test_mentions_counts_only_real_thread_mentions(self):
        # peter_legacy_mention's turn_complete row and the mention of Peter on
        # Adam's task must both stay out.
        assert self._list(mentions=self.me.id) == self._ids("peter_mention_me", "peter_slack_mention_me")
        assert self._list(mentions=self.peter.id) == self._ids("adam_mention_peter")

    def test_commented_by(self):
        assert self._list(commented_by=self.peter.id) == self._ids(
            "peter_mention_me", "peter_slack_mention_me", "mine_peter_commented"
        )
        assert self._list(commented_by=self.me.id) == self._ids("peter_i_commented")

    def test_pinned_is_the_requesters_pins(self):
        assert self._list(pinned="true") == self._ids("adam_pinned_by_me")

    def test_origin_product(self):
        assert self._list(origin_product="signals_scout") == self._ids("scout_in_channel")
        assert self._list(origin_product="slack") == self._ids("peter_slack_mention_me")

    @parameterized.expand(
        [
            ("failed", ["peter_mention_me"]),
            ("in_progress", ["peter_slack_mention_me", "adam_mention_peter", "mine_peter_commented"]),
            ("queued", ["scout_in_channel"]),
            ("cancelled", ["adam_pinned_by_me"]),
        ]
    )
    def test_status(self, value, expected):
        assert self._list(status=value) == self._ids(*expected)

    @parameterized.expand(
        [
            ("open", ["peter_mention_me"]),
            ("draft", ["mine_peter_commented"]),
            # merged matches pr_state plus the legacy pr_merged flag.
            ("merged", ["peter_plain", "peter_i_commented"]),
        ]
    )
    def test_pr_state(self, value, expected):
        assert self._list(pr_state=value) == self._ids(*expected)

    @parameterized.expand([("failing", ["peter_mention_me"]), ("passing", ["mine_peter_commented"])])
    def test_ci_status(self, value, expected):
        assert self._list(ci_status=value) == self._ids(*expected)

    def test_archived(self):
        assert self._list(archived="true") == self._ids("mine_archived")
        assert "mine_archived" not in {k for k in self.tasks if str(self.tasks[k].id) in self._list()}

    def test_channel_and_repository(self):
        assert self._list(channel=str(self.channel.id)) == self._ids("scout_in_channel")
        assert self._list(repository="posthog.com") == self._ids("scout_in_channel")

    def test_search(self):
        assert self._list(search="billing") == self._ids("peter_mention_me", "peter_plain")

    # ------------------------------------------------------------------
    # the combinations the query language produces
    # ------------------------------------------------------------------

    def test_mentions_me_by_peter_user_created(self):
        """`mentions:@me origin:user_created created-by:peter` — the exact
        query that surfaced unfiltered results on a backend without these
        params."""
        assert self._list(mentions=self.me.id, created_by=self.peter.id, origin_product="user_created") == self._ids(
            "peter_mention_me"
        )

    def test_created_by_and_status(self):
        assert self._list(created_by=self.peter.id, status="failed") == self._ids("peter_mention_me")

    def test_pinned_and_created_by(self):
        assert self._list(pinned="true", created_by=self.adam.id) == self._ids("adam_pinned_by_me")
        assert self._list(pinned="true", created_by=self.peter.id) == set()

    def test_commented_by_and_pr_state(self):
        assert self._list(commented_by=self.peter.id, pr_state="open") == self._ids("peter_mention_me")

    def test_search_and_mentions(self):
        assert self._list(search="billing", mentions=self.me.id) == self._ids("peter_mention_me")

    def test_status_and_ci(self):
        assert self._list(status="in_progress", ci_status="passing") == self._ids("mine_peter_commented")
