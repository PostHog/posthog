import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable
from products.mcp_analytics.backend.intent_topics.labeling import (
    TopicLabel,
    TopicLabelInput,
    build_label_prompt,
    fallback_label,
    label_topics,
)


def _candidate(topic_id: str, existing_label: str = "", samples: list[str] | None = None) -> TopicLabelInput:
    return TopicLabelInput(
        topic_id=topic_id, existing_label=existing_label, sample_intents=samples or ["create a trends insight"]
    )


class TestPrompt:
    def test_numbers_topics_and_keeps_existing_labels_visible(self) -> None:
        prompt = build_label_prompt([_candidate("t1", "Create insights", ["a", "b"]), _candidate("t2")])

        assert "Topic 1 (current label: Create insights)" in prompt
        assert "Topic 2 (current label: none)" in prompt
        assert "- a\n- b" in prompt

    def test_collapses_newlines_inside_a_sample(self) -> None:
        prompt = build_label_prompt([_candidate("t1", samples=["line one\nline two"])])

        assert "- line one line two" in prompt

    def test_fallback_label_never_echoes_intent_text(self) -> None:
        assert fallback_label("0193e5c2-1234-7abc-8def-000000000000") == "Topic 0193e5c2"


class TestLabelTopics(APIBaseTest):
    def _mock_client(self, payload: dict) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text=json.dumps(payload))
        return client

    @patch("products.mcp_analytics.backend.intent_topics.labeling.settings")
    @patch("products.mcp_analytics.backend.intent_topics.labeling.genai")
    def test_maps_numbered_answers_back_to_topic_ids(self, mock_genai, mock_settings) -> None:
        mock_settings.GEMINI_API_KEY = "key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_genai.Client.return_value = self._mock_client(
            {
                "topics": [
                    {"number": 1, "label": "Create insights", "summary": "Agents build charts."},
                    {"number": 2, "label": "List flags", "summary": "Agents read flags."},
                ]
            }
        )

        labels = label_topics(self.team, [_candidate("t1"), _candidate("t2")])

        assert labels == {
            "t1": TopicLabel(label="Create insights", summary="Agents build charts."),
            "t2": TopicLabel(label="List flags", summary="Agents read flags."),
        }

    @patch("products.mcp_analytics.backend.intent_topics.labeling.settings")
    @patch("products.mcp_analytics.backend.intent_topics.labeling.genai")
    def test_missing_or_blank_answers_fall_back_without_intent_text(self, mock_genai, mock_settings) -> None:
        mock_settings.GEMINI_API_KEY = "key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_genai.Client.return_value = self._mock_client({"topics": [{"number": 1, "label": "  ", "summary": ""}]})

        labels = label_topics(
            self.team, [_candidate("0193e5c2-aaaa", samples=["secret customer text"]), _candidate("0193e5c2-bbbb")]
        )

        assert labels["0193e5c2-aaaa"].label == "Topic 0193e5c2"
        assert labels["0193e5c2-bbbb"].label == "Topic 0193e5c2"
        assert "secret" not in json.dumps({k: v.label + v.summary for k, v in labels.items()})

    @patch("products.mcp_analytics.backend.intent_topics.labeling.settings")
    def test_requires_consent_and_a_key(self, mock_settings) -> None:
        mock_settings.GEMINI_API_KEY = ""
        try:
            label_topics(self.team, [_candidate("t1")])
        except IntentGenerationUnavailable:
            pass
        else:
            raise AssertionError("expected IntentGenerationUnavailable")

    def test_empty_candidates_make_no_call(self) -> None:
        assert label_topics(self.team, []) == {}
