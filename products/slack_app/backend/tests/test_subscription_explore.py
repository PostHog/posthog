from django.test import TestCase

from parameterized import parameterized

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES, bot_is_ready
from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team


class TestBotIsReady(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.org, name="Team")

    def _integration(self, scopes: frozenset[str]) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={"scope": ",".join(sorted(scopes))},
            sensitive_config={"access_token": "xoxb-test"},
        )

    @parameterized.expand(
        [
            ("full_scopes", REQUIRED_SLACK_SCOPES, True),
            ("missing_scopes", frozenset({"chat:write"}), False),
        ]
    )
    def test_bot_is_ready(self, _name: str, scopes: frozenset[str], expected: bool) -> None:
        assert bot_is_ready(self._integration(scopes)) is expected


class TestBuildExploreHint(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.org, name="Team")

    def _integration(self, scopes: frozenset[str]) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T1",
            config={"scope": ",".join(sorted(scopes))},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def test_no_integration_returns_none(self) -> None:
        assert build_explore_hint(None, utm_tags="utm", ai_enabled=True) is None

    def test_ai_disabled_returns_none(self) -> None:
        # Org hasn't approved AI data processing — don't nudge toward the AI bot, even with a ready install.
        assert build_explore_hint(self._integration(REQUIRED_SLACK_SCOPES), utm_tags="utm", ai_enabled=False) is None

    def test_bot_ready_nudges_mention(self) -> None:
        hint = build_explore_hint(self._integration(REQUIRED_SLACK_SCOPES), utm_tags="utm", ai_enabled=True)
        assert hint is not None
        assert hint["type"] == "context"
        assert "@PostHog" in hint["elements"][0]["text"]

    def test_bot_not_ready_links_docs(self) -> None:
        hint = build_explore_hint(self._integration(frozenset({"chat:write"})), utm_tags="utm", ai_enabled=True)
        assert hint is not None
        text = hint["elements"][0]["text"]
        assert "docs/slack-app?utm" in text
        assert "Reply in this thread" not in text
