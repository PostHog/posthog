import json

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.types import FeatureFlagResult

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend import feature_flags
from products.slack_app.backend.logic import message_sentiment
from products.slack_app.backend.logic.message_sentiment import (
    DEFAULT_FRUSTRATION_GIF_URLS,
    UNHAPPY_REACTION,
    Sentiment,
    SentimentResponseRequest,
    SentimentResult,
    SentimentVerdict,
    respond_to_sentiment,
)


class TestAllowedGifUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("posthog_cloudinary", "https://res.cloudinary.com/dmukukwp6/image/upload/calm.gif", True),
            ("plain_http", "http://res.cloudinary.com/dmukukwp6/image/upload/calm.gif", False),
            ("other_host", "https://attacker.example/scam.gif", False),
            ("other_cloudinary_account", "https://res.cloudinary.com/someone-else/image/upload/x.gif", False),
            ("userinfo_trick", "https://res.cloudinary.com@evil.example/dmukukwp6/x.gif", False),
            ("lookalike_host", "https://res.cloudinary.com.evil.example/dmukukwp6/x.gif", False),
            ("not_a_string", 3, False),
        ]
    )
    def test_only_posthog_assets_pass(self, _name, url, allowed):
        assert feature_flags.is_allowed_gif_url(url) is allowed


class TestSentimentVerdict(SimpleTestCase):
    @parameterized.expand(
        [
            ("calm_pick_needs_no_bar", "confused", 0.46, {"confused": 0.46, "neutral": 0.38}, Sentiment.CONFUSED),
            (
                "unhappy_split_reads_the_likelier_option",
                "frustrated",
                0.46,
                {"frustrated": 0.46, "not_happy": 0.23, "neutral": 0.31},
                Sentiment.FRUSTRATED,
            ),
            (
                "unhappy_tie_reads_not_happy",
                "frustrated",
                0.3,
                {"frustrated": 0.3, "not_happy": 0.3, "neutral": 0.4},
                Sentiment.NOT_HAPPY,
            ),
            (
                "unhappy_pick_below_the_bar_reads_neutral",
                "frustrated",
                0.35,
                {"frustrated": 0.35, "neutral": 0.33, "happy": 0.32},
                Sentiment.NEUTRAL,
            ),
            ("unknown_choice_reads_neutral", "angry", 0.99, {"angry": 0.99}, Sentiment.NEUTRAL),
            ("pick_without_distribution_uses_its_confidence", "frustrated", 0.93, {}, Sentiment.FRUSTRATED),
        ]
    )
    def test_sentiment(self, _name, choice, confidence, probabilities, expected):
        assert SentimentVerdict(choice=choice, confidence=confidence, probabilities=probabilities).sentiment == expected


def _model(choice: str) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(
        model="m",
        answers={"sentiment": ChoiceAnswer(choice=choice, confidence=0.9, probabilities={choice: 0.9})},
        input_tokens=None,
    )
    return client


def _flags(response: bool, gif_urls: list[str] | None, gif_flag: bool | None = None) -> dict[str, FeatureFlagResult]:
    def result(key: str, enabled: bool, payload: object = None) -> FeatureFlagResult:
        return FeatureFlagResult(key=key, enabled=enabled, variant=None, payload=payload, reason=None)

    return {
        feature_flags.SLACK_APP_FRUSTRATION_RESPONSE_FLAG: result(
            feature_flags.SLACK_APP_FRUSTRATION_RESPONSE_FLAG, response
        ),
        feature_flags.SLACK_APP_FRUSTRATION_GIF_FLAG: result(
            feature_flags.SLACK_APP_FRUSTRATION_GIF_FLAG,
            gif_urls is not None if gif_flag is None else gif_flag,
            json.dumps({"gif_urls": gif_urls}) if gif_urls is not None else None,
        ),
    }


@pytest.mark.django_db
class TestRespondToSentiment:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=organization, name="Team")
        self.integration = Integration.objects.create(
            team=team, kind="slack", integration_id="T_SENTIMENT", sensitive_config={"access_token": "xoxb-test"}
        )
        with (
            patch.object(message_sentiment, "SlackIntegration") as slack,
            patch.object(message_sentiment, "capture_slack_event") as self.capture,
        ):
            self.slack_client = slack.return_value.client
            yield

    def _respond(
        self,
        flags: dict[str, FeatureFlagResult],
        choice: str,
        *,
        model_error: Exception | None = None,
        privacy_mode: bool = False,
    ) -> SentimentResult | None:
        with (
            patch.object(
                feature_flags.posthoganalytics, "feature_enabled", side_effect=lambda key, *a, **k: flags[key].enabled
            ),
            patch.object(
                feature_flags.posthoganalytics, "get_feature_flag_result", side_effect=lambda key, *a, **k: flags[key]
            ),
            patch.object(
                message_sentiment, "build_system_one_client", return_value=_model(choice), side_effect=model_error
            ) as build,
            patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=privacy_mode),
        ):
            sentiment = respond_to_sentiment(
                SentimentResponseRequest(
                    integration=self.integration,
                    slack_user_id="U_READER",
                    posthog_user=None,
                    channel="C1",
                    thread_ts="1.1",
                    person_message="third time asking, the signup count is still wrong",
                    person_message_ts="2.2",
                    run_id=None,
                    trace_id=None,
                )
            )
        self.model_built = build.called
        self.model_privacy_mode = build.call_args.kwargs.get("privacy_mode") if build.called else None
        return sentiment

    def _events(self) -> list[str]:
        return [call.args[1] for call in self.capture.call_args_list]

    @parameterized.expand(
        [
            ("happy", "happy", False, None),
            ("confused", "confused", False, None),
            ("not_happy_gets_no_gif", "not_happy", True, None),
            ("frustrated_gets_a_gif", "frustrated", True, "https://res.cloudinary.com/dmukukwp6/image/upload/calm.gif"),
        ]
    )
    def test_reaction_and_gif_follow_the_sentiment(self, _name, choice, reacted, gif_url):
        gifs = ["https://example.com/elsewhere.gif", "https://res.cloudinary.com/dmukukwp6/image/upload/calm.gif"]

        assert self._respond(_flags(True, gifs), choice) == SentimentResult(sentiment=Sentiment(choice))

        assert self.slack_client.reactions_add.called is reacted
        if reacted:
            assert self.slack_client.reactions_add.call_args.kwargs["name"] == UNHAPPY_REACTION
        posted = self.slack_client.chat_postEphemeral.call_args
        assert (posted.kwargs["blocks"][0]["image_url"] if posted else None) == gif_url
        assert self.capture.call_args_list[0].kwargs["sentiment"] == choice

    def test_frustrated_without_the_gif_flag_gets_only_the_reaction(self):
        assert self._respond(_flags(True, None), "frustrated") == SentimentResult(sentiment=Sentiment.FRUSTRATED)

        self.slack_client.reactions_add.assert_called_once()
        self.slack_client.chat_postEphemeral.assert_not_called()
        assert self._events() == ["slack app message sentiment classified"]

    def test_gif_flag_without_a_payload_uses_the_default_gifs(self):
        assert self._respond(_flags(True, None, gif_flag=True), "frustrated") == SentimentResult(
            sentiment=Sentiment.FRUSTRATED
        )

        image = self.slack_client.chat_postEphemeral.call_args.kwargs["blocks"][0]["image_url"]
        assert image in DEFAULT_FRUSTRATION_GIF_URLS

    def test_flag_off_runs_no_model(self):
        assert (
            self._respond(_flags(False, ["https://res.cloudinary.com/dmukukwp6/image/upload/calm.gif"]), "frustrated")
            is None
        )

        assert self.model_built is False
        self.slack_client.reactions_add.assert_not_called()
        assert self._events() == []

    def test_a_failed_model_call_is_a_calm_verdict_not_a_missing_one(self):
        # None would make the interview checks call the failing model a second time.
        result = self._respond(_flags(True, None), "frustrated", model_error=TimeoutError())

        assert result == SentimentResult(sentiment=None)
        self.slack_client.reactions_add.assert_not_called()

    @parameterized.expand([("privacy_on", True), ("privacy_off", False)])
    def test_the_model_call_follows_the_organizations_privacy_mode(self, _name, privacy_mode):
        self._respond(_flags(True, None), "neutral", privacy_mode=privacy_mode)

        assert self.model_privacy_mode is privacy_mode
