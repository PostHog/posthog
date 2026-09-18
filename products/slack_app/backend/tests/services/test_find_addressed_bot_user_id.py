import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services.slack_user_info import find_addressed_bot_user_id

OUR_BOT = "U0OURBOT"


class TestFindAddressedBotUserId:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SLACK",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self._cache_profile(OUR_BOT, is_bot=True)
        self._cache_profile("U0OTHERAPP", is_bot=True)
        self._cache_profile("U0ALICE", is_bot=False)

    def _cache_profile(self, slack_user_id: str, *, is_bot: bool) -> None:
        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id=slack_user_id,
            display_name=slack_user_id,
            is_bot=is_bot,
            refreshed_at=timezone.now(),
        )

    def _find(self, text: str) -> str | None:
        with patch(
            "products.slack_app.backend.services.slack_user_info.get_cached_bot_user_id",
            return_value=OUR_BOT,
        ):
            return find_addressed_bot_user_id(SlackIntegration(self.integration), self.integration, text)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param("<@U0OTHERAPP> take another look", "U0OTHERAPP", id="another_app"),
            pytest.param("<@U0OTHERAPP|other agent> take another look", "U0OTHERAPP", id="labeled_mention"),
            pytest.param("<@U0ALICE> can you take this one", None, id="a_teammate"),
            pytest.param("<@U0OURBOT> fix the export filter", None, id="our_own_bot"),
            pytest.param("i like <@U0OTHERAPP> and i like <@U0OURBOT>", None, id="our_own_bot_and_another_app"),
            pytest.param("<@U0ALICE> and <@U0OTHERAPP> already looked", "U0OTHERAPP", id="a_teammate_and_an_app"),
            pytest.param("could you also check the export filter", None, id="no_mention"),
            pytest.param("<@U0OTHERAPP>/checkout-sdk still fails", "U0OTHERAPP", id="package_path"),
        ],
    )
    def test_answers_which_mention_belongs_to_another_app(self, text, expected):
        assert self._find(text) == expected

    def test_an_unresolvable_mention_answers_none(self):
        # A Slack outage must not silence a genuine follow-up, so an id we cannot classify
        # is treated as no evidence at all.
        with (
            patch(
                "products.slack_app.backend.services.slack_user_info.get_cached_bot_user_id",
                return_value=OUR_BOT,
            ),
            patch(
                "products.slack_app.backend.services.slack_user_info.get_slack_user_info",
                side_effect=RuntimeError("slack hiccup"),
            ),
        ):
            result = find_addressed_bot_user_id(
                SlackIntegration(self.integration), self.integration, "<@U0UNKNOWN> take another look"
            )
        assert result is None

    def test_an_unresolvable_own_bot_id_answers_none(self):
        # Our own mention is indistinguishable from another app's without our id, and the
        # webhook lets a tagged reply through on the same failure, so dropping it here
        # would silently swallow a message that did tag us.
        with patch(
            "products.slack_app.backend.services.slack_user_info.get_cached_bot_user_id",
            return_value=None,
        ):
            result = find_addressed_bot_user_id(
                SlackIntegration(self.integration), self.integration, "<@U0OTHERAPP> take another look"
            )
        assert result is None
