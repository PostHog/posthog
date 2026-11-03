from unittest.mock import MagicMock, patch

from django.test import override_settings

from openai import OpenAI

from ee.surveys.summaries.headline_summary import _headline_client


@patch("ee.surveys.summaries.headline_summary.build_openai_client")
def test_headline_calls_openai_directly_without_the_ai_gateway(mock_build_openai_client: MagicMock) -> None:
    with (
        override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""),
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
    ):
        client = _headline_client(MagicMock(id="survey-1"), MagicMock(id=7), MagicMock(distinct_id="user-1"))

    assert isinstance(client, OpenAI)
    mock_build_openai_client.assert_not_called()


def test_headline_through_the_ai_gateway_is_private_and_unbilled() -> None:
    with override_settings(AI_GATEWAY_URL="https://gateway.test/v1", AI_GATEWAY_API_KEY="phs_test"):
        client = _headline_client(MagicMock(id="survey-1"), MagicMock(id=7), MagicMock(distinct_id="user-1"))

    assert str(client.base_url).startswith("https://gateway.test/v1")
    assert client.default_headers["X-PostHog-Billable"] == "false"
    assert client.default_headers["X-PostHog-Privacy-Mode"] == "true"
    assert client.default_headers["X-PostHog-Product"] == "surveys"
