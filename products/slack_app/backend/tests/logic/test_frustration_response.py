import json

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from posthoganalytics.types import FeatureFlagResult

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend import feature_flags
from products.slack_app.backend.logic import frustration_response, interview_recruitment
from products.slack_app.backend.logic.frustration_response import (
    FRUSTRATION_REACTION,
    FrustrationResponseRequest,
    respond_to_frustration,
)

RUN_ID = "4f7c2a51-8a5b-4f1e-9d55-0c2a7d9e1b10"


def _model(choice: str) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(
        model="m",
        answers={"sentiment": ChoiceAnswer(choice=choice, confidence=0.9, probabilities={})},
        input_tokens=None,
    )
    return client


def _flag(enabled: bool, payload: object = None) -> FeatureFlagResult:
    return FeatureFlagResult(
        key=feature_flags.SLACK_APP_FRUSTRATION_RESPONSE_FLAG,
        enabled=enabled,
        variant=None,
        payload=payload,
        reason=None,
    )


@pytest.mark.django_db
class TestRespondToFrustration:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=organization, name="Team")
        self.integration = Integration.objects.create(
            team=team, kind="slack", integration_id="T_FRUSTRATION", sensitive_config={"access_token": "xoxb-test"}
        )
        with (
            patch.object(frustration_response, "SlackIntegration") as slack,
            patch.object(frustration_response, "capture_slack_event") as self.capture,
        ):
            self.slack_client = slack.return_value.client
            yield

    def _respond(self, flag: FeatureFlagResult, model: MagicMock) -> str:
        with (
            patch.object(feature_flags.posthoganalytics, "get_feature_flag_result", return_value=flag),
            patch.object(interview_recruitment, "build_system_one_client", return_value=model) as build,
        ):
            outcome = respond_to_frustration(
                FrustrationResponseRequest(
                    integration=self.integration,
                    slack_user_id="U_READER",
                    posthog_user=None,
                    channel="C1",
                    thread_ts="1.1",
                    person_message="this is the third time you got the funnel wrong",
                    person_message_ts="2.2",
                    run_id=RUN_ID,
                    trace_id=None,
                )
            )
        self.model_built = build.called
        return outcome

    @parameterized.expand(
        [
            (
                "payload_as_json_string",
                json.dumps({"gif_urls": ["https://example.com/calm.gif"]}),
                "https://example.com/calm.gif",
            ),
            ("unsafe_urls_dropped", {"gif_urls": ["http://example.com/plain.gif", 3]}, None),
        ]
    )
    def test_an_unhappy_reader_gets_a_bow_and_an_apology(self, _name, payload, gif_url):
        assert self._respond(_flag(True, payload), _model("unhappy")) == "responded"

        self.slack_client.reactions_add.assert_called_once_with(
            channel="C1", timestamp="2.2", name=FRUSTRATION_REACTION
        )
        blocks = {block["type"]: block for block in self.slack_client.chat_postEphemeral.call_args.kwargs["blocks"]}
        assert blocks.get("image", {}).get("image_url") == gif_url
        button = json.loads(blocks["actions"]["elements"][0]["value"])
        assert button == {
            "integration_id": self.integration.id,
            "run_id": RUN_ID,
            "sentiment": "negative",
            "source": "frustration_response",
        }
        assert self.capture.call_args.args[1] == "slack app frustration response shown"

    @parameterized.expand(
        [
            ("flag_off", _flag(False), "skipped", False),
            ("calm_reader", _flag(True), "calm", True),
        ]
    )
    def test_no_response_without_flag_and_unhappy_verdict(self, _name, flag, outcome, model_built):
        assert self._respond(flag, _model("not_unhappy")) == outcome

        assert self.model_built is model_built
        self.slack_client.reactions_add.assert_not_called()
        self.slack_client.chat_postEphemeral.assert_not_called()
