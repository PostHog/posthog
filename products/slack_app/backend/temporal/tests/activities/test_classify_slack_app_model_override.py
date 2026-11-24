from unittest.mock import MagicMock, patch

from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.backend.temporal.activities.classifiers import classify_slack_app_model_override
from products.slack_app.backend.temporal.slack_app_mention_processing import POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS
from products.slack_app.backend.temporal.types import SlackAppModelOverride

CHOICES = (
    ModelChoice("claude", "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "max")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "max")),
)
BUILD_CLIENT = "products.tasks.backend.logic.model_override.build_ai_gateway_openai_client"


class TestClassifySlackAppModelOverride:
    def test_returns_requested_choice(self):
        with patch(
            BUILD_CLIENT, return_value=self._fake_client('{"model": "claude-fable-5", "reasoning_effort": "high"}')
        ):
            override = classify_slack_app_model_override("use fable for this", CHOICES)

        assert override == SlackAppModelOverride(model="claude-fable-5", reasoning_effort="high")

    def test_call_is_bounded_so_a_slow_gateway_falls_back(self):
        # The gateway client's own defaults are a 600s read and two retries. Unbounded,
        # the activity's 600s deadline expires first, so the mention fails outright
        # instead of taking the fallback this classifier is built around.
        fake_client = self._fake_client('{"model": null, "reasoning_effort": null}')
        with patch(BUILD_CLIENT, return_value=fake_client):
            classify_slack_app_model_override("use fable for this", CHOICES)

        assert fake_client.with_options.called, "the classifier must bound the gateway client"
        options = fake_client.with_options.call_args.kwargs
        assert options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS
        assert options["max_retries"] * options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

    def test_prompt_snapshot_matches(self, snapshot):
        # The prompt is the whole classifier: the catalogue it offers, the
        # instruction-vs-subject-matter examples, and the reply contract. Pinning it means
        # a reworded rule shows up as a reviewable diff in the ``.ambr`` snapshot rather
        # than as a silent behaviour change. Update intentionally by re-running with
        # ``--snapshot-update`` after auditing the diff.
        fake_client = self._fake_client('{"model": null, "reasoning_effort": null}')
        with patch(BUILD_CLIENT, return_value=fake_client):
            classify_slack_app_model_override("use fable for this one and fix the checkout test", CHOICES)

        assert fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"] == snapshot

    def _fake_client(self, content: str) -> MagicMock:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        client = MagicMock()
        # `with_options` returns a configured copy, so the fake hands back itself to keep
        # one set of call records no matter how the call site bounds the client.
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        return client
