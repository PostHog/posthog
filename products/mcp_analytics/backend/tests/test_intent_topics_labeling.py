import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

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
        assert fallback_label("0193e5c2-1234-7abc-8def-000000000000") == "Topic 00000000"

    def test_topics_created_together_get_different_fallback_labels(self) -> None:
        # UUIDv7 ids made in the same second share their leading timestamp bits.
        assert fallback_label("0193e5c2-1234-7abc-8def-0000000000aa") != fallback_label(
            "0193e5c2-1234-7abc-8def-0000000000bb"
        )


class TestLabelTopics(APIBaseTest):
    def _mock_client(self, payload: dict) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text=json.dumps(payload))
        return client

    @patch("products.mcp_analytics.backend.intent_topics.labeling.build_gemini_client")
    def test_maps_numbered_answers_back_to_topic_ids(self, mock_build_client) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_build_client.return_value = self._mock_client(
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

    @patch("products.mcp_analytics.backend.intent_topics.labeling.build_gemini_client")
    def test_missing_or_blank_answers_fall_back_without_intent_text(self, mock_build_client) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_build_client.return_value = self._mock_client({"topics": [{"number": 1, "label": "  ", "summary": ""}]})

        labels = label_topics(
            self.team,
            [
                _candidate("0193e5c2-1234-7abc-8def-0000000000aa", samples=["secret customer text"]),
                _candidate("0193e5c2-1234-7abc-8def-0000000000bb"),
            ],
        )

        assert labels["0193e5c2-1234-7abc-8def-0000000000aa"].label == "Topic 000000aa"
        assert labels["0193e5c2-1234-7abc-8def-0000000000bb"].label == "Topic 000000bb"
        assert "secret" not in json.dumps({k: v.label + v.summary for k, v in labels.items()})

    @patch("products.mcp_analytics.backend.intent_topics.labeling.build_gemini_client")
    def test_sample_intents_stay_out_of_ai_telemetry(self, mock_build_client) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_build_client.return_value = self._mock_client(
            {"topics": [{"number": 1, "label": "Create insights", "summary": "Charts."}]}
        )

        label_topics(self.team, [_candidate("t1")])

        assert mock_build_client.call_args.kwargs["privacy_mode"] is True

    @parameterized.expand([("no_consent", False, MagicMock()), ("no_gateway", True, None)])
    @patch("products.mcp_analytics.backend.intent_topics.labeling.build_gemini_client")
    def test_requires_consent_and_a_gateway(self, _name, approved, client, mock_build_client) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        mock_build_client.return_value = client
        try:
            label_topics(self.team, [_candidate("t1")])
        except IntentGenerationUnavailable:
            pass
        else:
            raise AssertionError("expected IntentGenerationUnavailable")

    def test_empty_candidates_make_no_call(self) -> None:
        assert label_topics(self.team, []) == {}
