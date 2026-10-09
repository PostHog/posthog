import hmac
import json
import hashlib
from itertools import count
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.github_commands.backend.logic.commands import CommandContext, PullRequestFacts
from products.github_commands.backend.logic.dispatch import dispatch_comment_command
from products.github_commands.backend.logic.github import Reaction
from products.github_commands.backend.logic.handlers import handle_loop
from products.github_commands.backend.logic.intake import CommentCommandRequest

INSTALLATION_ID = "31337"
REPOSITORY = "acme/widgets"
FLAG = "products.github_commands.backend.logic.dispatch.posthog_feature_flag_enabled"
REQUEST_STAMPHOG_REVIEW = "products.github_commands.backend.logic.handlers.stamphog_requests.request_review"
LIST_LOOPS = "products.github_commands.backend.logic.handlers.loops_facade.list_loops"
FIRE_LOOP = "products.github_commands.backend.logic.handlers.loops_facade.fire_loop_api_for_user"
RUN_COMMENT_COMMAND = "products.github_commands.backend.tasks.tasks.run_comment_command.delay"

# Each test gets its own commenter, so the per-commenter rate limit in Redis never carries over.
_github_ids = count(10_000)


class FakeGitHub:
    def __init__(self, *, permission: str = "write", pull_request: PullRequestFacts | None = None) -> None:
        self.permission = permission
        self.pull_request_facts = pull_request or _pull_request()
        self.reactions: list[Reaction] = []
        self.replies: list[str] = []

    def collaborator_permission(self, repository: str, login: str) -> str:
        return self.permission

    def pull_request(self, repository: str, number: int) -> PullRequestFacts | None:
        return self.pull_request_facts

    def react(self, repository: str, comment_id: int, reaction: Reaction) -> None:
        self.reactions.append(reaction)

    def reply(self, repository: str, number: int, body: str) -> None:
        self.replies.append(body)


def _pull_request(**overrides: Any) -> PullRequestFacts:
    values: dict[str, Any] = {
        "repository": REPOSITORY,
        "number": 7,
        "url": f"https://github.com/{REPOSITORY}/pull/7",
        "state": "open",
        "draft": False,
        "head_sha": "abc123",
        "head_branch": "feature/thing",
        "is_fork": False,
    }
    values.update(overrides)
    return PullRequestFacts(**values)


class TestDispatchCommentCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.github_id = next(_github_ids)
        Integration.objects.create(team=self.team, kind="github", integration_id=INSTALLATION_ID, config={})
        self.flag = self.enterContext(patch(FLAG, return_value=True))

    def _request(self, verb: str = "stamp", argument: str = "", comment_id: int = 555) -> CommentCommandRequest:
        return CommentCommandRequest(
            installation_id=INSTALLATION_ID,
            repository=REPOSITORY,
            pr_number=7,
            comment_id=comment_id,
            comment_url=f"https://github.com/{REPOSITORY}/pull/7#issuecomment-{comment_id}",
            commenter_github_id=self.github_id,
            commenter_login="octo",
            verb=verb,
            argument=argument,
        )

    def _link_github_login(self) -> None:
        UserSocialAuth.objects.create(user=self.user, provider="github", uid=str(self.github_id))

    @parameterized.expand([("read",), ("none",)])
    def test_a_commenter_without_write_access_gets_no_answer_and_nothing_runs(self, permission: str) -> None:
        self._link_github_login()
        github = FakeGitHub(permission=permission)

        with patch(REQUEST_STAMPHOG_REVIEW) as request_review:
            outcome = dispatch_comment_command(self._request(), github=github)

        assert outcome == "no_write_access"
        assert github.reactions == [] and github.replies == []
        request_review.assert_not_called()

    def test_a_linked_member_runs_the_command_as_themselves(self) -> None:
        self._link_github_login()
        github = FakeGitHub()

        with patch(REQUEST_STAMPHOG_REVIEW, return_value=MagicMock(created=True)) as request_review:
            outcome = dispatch_comment_command(self._request(), github=github)

        assert outcome == "accepted"
        request_review.assert_called_once_with(self.team.id, user_id=self.user.id, repository=REPOSITORY, pr_number=7)
        assert github.reactions == ["eyes", "rocket"]
        assert github.replies == ["<!-- posthog-github-command:555 -->\n@octo Stamphog is reviewing this pull request."]

    @parameterized.expand(
        [
            # A GitHub login saved on a project integration is not proof of owning the account.
            ("login_only", "team_integration_login"),
            ("nothing", None),
        ]
    )
    def test_only_a_github_verified_link_identifies_the_commenter(self, _name: str, link: str | None) -> None:
        if link == "team_integration_login":
            Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="other",
                created_by=self.user,
                config={"connecting_user_github_login": "octo"},
            )
        github = FakeGitHub()

        with patch(REQUEST_STAMPHOG_REVIEW) as request_review:
            outcome = dispatch_comment_command(self._request(), github=github)

        assert outcome == "unlinked"
        request_review.assert_not_called()
        assert "not linked to a PostHog account" in github.replies[0]

    def test_a_connected_github_account_identifies_the_commenter_by_id(self) -> None:
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="1",
            config={"github_user": {"login": "renamed-since", "id": self.github_id}},
        )

        with patch(REQUEST_STAMPHOG_REVIEW, return_value=MagicMock(created=True)):
            outcome = dispatch_comment_command(self._request(), github=FakeGitHub())

        assert outcome == "accepted"

    def test_a_comment_runs_at_most_once(self) -> None:
        self._link_github_login()

        with patch(REQUEST_STAMPHOG_REVIEW, return_value=MagicMock(created=True)) as request_review:
            first = dispatch_comment_command(self._request(), github=FakeGitHub())
            second = dispatch_comment_command(self._request(), github=FakeGitHub())

        assert (first, second) == ("accepted", "duplicate")
        request_review.assert_called_once()

    @parameterized.expand(
        [
            ("fork", _pull_request(is_fork=True), "fork_refused"),
            ("closed", _pull_request(state="closed"), "pull_request_closed"),
        ]
    )
    def test_refuses_pull_requests_a_command_must_not_touch(
        self, _name: str, pull_request: PullRequestFacts, expected: str
    ) -> None:
        self._link_github_login()

        with patch(REQUEST_STAMPHOG_REVIEW) as request_review:
            outcome = dispatch_comment_command(self._request(), github=FakeGitHub(pull_request=pull_request))

        assert outcome == expected
        request_review.assert_not_called()

    def test_an_installation_outside_the_rollout_stays_silent(self) -> None:
        self._link_github_login()
        self.flag.return_value = False
        github = FakeGitHub()

        with patch(REQUEST_STAMPHOG_REVIEW) as request_review:
            outcome = dispatch_comment_command(self._request(), github=github)

        assert outcome == "not_rolled_out"
        assert github.reactions == [] and github.replies == []
        request_review.assert_not_called()

    def test_loop_refuses_a_loop_the_commenter_does_not_own(self) -> None:
        context = CommandContext(
            request=self._request(verb="loop", argument="Triage PR"),
            pull_request=_pull_request(),
            user_id=self.user.id,
            team_ids=(self.team.id,),
        )
        teammates_loop = SimpleNamespace(id="loop-1", name="triage pr", created_by_id=self.user.id + 1)

        with patch(LIST_LOOPS, return_value=[teammates_loop]), patch(FIRE_LOOP) as fire:
            outcome = handle_loop(context)

        assert not outcome.accepted
        fire.assert_not_called()

    @patch("posthog.ingress.github.provider.get_instance_setting", return_value="test-webhook-secret")
    def test_a_signed_comment_with_a_command_is_queued(self, _secret: MagicMock) -> None:
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)
        payload = {
            "action": "created",
            "installation": {"id": int(INSTALLATION_ID)},
            "repository": {"full_name": REPOSITORY},
            "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/repos/acme/widgets/pulls/7"}},
            "comment": {
                "id": 555,
                "html_url": f"https://github.com/{REPOSITORY}/pull/7#issuecomment-555",
                "body": "@posthog review",
                "author_association": "MEMBER",
                "user": {"id": self.github_id, "login": "octo", "type": "User"},
            },
        }
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()

        with patch(RUN_COMMENT_COMMAND) as delay:
            response = self.client.post(
                "/webhooks/github/",
                data=body,
                content_type="application/json",
                headers={
                    "X-Hub-Signature-256": signature,
                    "X-GitHub-Event": "issue_comment",
                    "X-GitHub-Delivery": "d1",
                },
            )

        assert response.status_code == 202
        delay.assert_called_once()
        assert delay.call_args.kwargs["verb"] == "review"
        assert delay.call_args.kwargs["commenter_github_id"] == self.github_id
