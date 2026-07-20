from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.http import HttpRequest
from django.test import SimpleTestCase, override_settings

from products.signals.backend.github_mention import webhook

PR_URL = "https://github.com/acme/app/pull/7"


def _request() -> HttpRequest:
    return cast(HttpRequest, SimpleNamespace(headers={"X-GitHub-Delivery": "abc-123"}, body=b"{}"))


def _payload(*, action: str = "created", body: str = "@posthog please fix", is_pr: bool = True, via_app=None):
    issue = {"pull_request": {"html_url": PR_URL}} if is_pr else {}
    return {
        "action": action,
        "issue": issue,
        "comment": {"id": 55, "body": body, "user": {"id": 999, "login": "octo"}, "performed_via_github_app": via_app},
        "repository": {"full_name": "acme/app"},
        "installation": {"id": 42},
    }


@override_settings(GITHUB_APP_SLUG="posthog")
class TestHandleGitHubMentionEvent(SimpleTestCase):
    def setUp(self) -> None:
        self.resolve = patch.object(webhook.tasks_facade, "resolve_signal_pr_mention_context").start()
        self.resolve.return_value = SimpleNamespace(team_id=1)
        self.delay = patch.object(webhook.process_github_mention, "delay").start()
        cache_patch = patch.object(webhook, "cache")
        self.cache = cache_patch.start()
        self.cache.add.return_value = True
        self.cache.get.return_value = None  # comment not already handled directly by the report-view endpoint
        self.addCleanup(patch.stopall)

    def test_enqueues_on_bot_mention_on_signals_pr(self) -> None:
        webhook.handle_github_mention_event(_request(), _payload())

        self.delay.assert_called_once()
        self.assertEqual(self.delay.call_args.kwargs["team_id"], 1)
        self.assertEqual(self.delay.call_args.kwargs["commenter_account_id"], 999)

    def test_does_not_enqueue_when_not_a_signals_pr(self) -> None:
        self.resolve.return_value = None
        webhook.handle_github_mention_event(_request(), _payload())
        self.delay.assert_not_called()

    def test_does_not_enqueue_for_bot_authored_comment(self) -> None:
        webhook.handle_github_mention_event(_request(), _payload(via_app={"id": 1}))
        self.delay.assert_not_called()

    def test_does_not_enqueue_without_mention(self) -> None:
        webhook.handle_github_mention_event(_request(), _payload(body="looks good, merging"))
        self.delay.assert_not_called()

    def test_does_not_enqueue_on_edited_action(self) -> None:
        webhook.handle_github_mention_event(_request(), _payload(action="edited"))
        self.delay.assert_not_called()

    def test_does_not_enqueue_for_plain_issue_comment(self) -> None:
        webhook.handle_github_mention_event(_request(), _payload(is_pr=False))
        self.delay.assert_not_called()

    def test_does_not_enqueue_on_duplicate_delivery(self) -> None:
        self.cache.add.return_value = False
        webhook.handle_github_mention_event(_request(), _payload())
        self.delay.assert_not_called()

    def test_does_not_enqueue_when_comment_already_handled_directly(self) -> None:
        # The report-view endpoint marks the comment id before the webhook delivers it, so the
        # user-authored comment it posted doesn't trigger a second run here.
        self.cache.get.return_value = True
        webhook.handle_github_mention_event(_request(), _payload())
        self.delay.assert_not_called()
