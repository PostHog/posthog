"""Tests for failure fingerprinting and LLM-backed classification.

Fingerprinting is a pure function — covered without Django. Classification hits an LLM boundary,
which is mocked; no test calls the real API.
"""

import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.mcp_analytics.backend.failure_classification import (
    CLASSIFY_BATCH_SIZE,
    FailureClass,
    FailureClassificationUnavailable,
    classify_fingerprints,
    normalize_fingerprint,
)


class TestNormalizeFingerprint:
    @parameterized.expand(
        [
            (
                "uuid",
                "Resource 123e4567-e89b-12d3-a456-426614174000 not found",
                "resource not found",
            ),
            ("email", "No account for user@example.com", "no account for"),
            ("url", "fetch failed: https://api.example.com/v1/things?id=1", "fetch failed:"),
            (
                "double_quoted_value",
                'Invalid arguments: "some-tool-name" is not a valid tool',
                "invalid arguments: is not a valid tool",
            ),
            ("single_quoted_value", "Field 'email' is required", "field is required"),
            ("numbers", "timed out after 45000ms, retried 3 times", "timed out after ms, retried times"),
            ("iso_date", "Rate limited until 2026-08-06T12:00:00Z", "rate limited until"),
            ("whitespace", "tool   failed\n\nwith   no cause", "tool failed with no cause"),
        ]
    )
    def test_strips_variable_content(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_fingerprint(raw) == expected

    def test_truncates_to_200_chars(self) -> None:
        assert len(normalize_fingerprint("x" * 500)) == 200

    def test_translation_stays_a_distinct_fingerprint(self) -> None:
        # Fingerprinting groups occurrences of the same wording; it must not merge a message
        # with its translation, which classify_fingerprints treats as separate inputs.
        english = normalize_fingerprint("The email field is required")
        portuguese = normalize_fingerprint("O campo email é obrigatório")

        assert english != portuguese


def _openai_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


def _classification_payload(fingerprints: list[str], failure_class: str) -> str:
    return json.dumps(
        {"classifications": [{"line_number": i + 1, "failure_class": failure_class} for i in range(len(fingerprints))]}
    )


class TestClassifyFingerprints(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def test_raises_without_ai_processing_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch("products.mcp_analytics.backend.failure_classification.OpenAI") as mock_openai_cls:
            with self.assertRaises(FailureClassificationUnavailable):
                classify_fingerprints({"a fingerprint": "a raw message"}, self.team)

        mock_openai_cls.return_value.chat.completions.create.assert_not_called()

    def test_returns_mapping_from_fingerprint_to_class(self) -> None:
        items = {
            "timed out after seconds": "Error: timed out after 45 seconds",
            "resource not found": "Resource 123 not found",
        }
        payload = json.dumps(
            {
                "classifications": [
                    {"line_number": 1, "failure_class": "timeout"},
                    {"line_number": 2, "failure_class": "resource_not_found"},
                ]
            }
        )
        with patch("products.mcp_analytics.backend.failure_classification.OpenAI") as mock_openai_cls:
            mock_create = mock_openai_cls.return_value.chat.completions.create
            mock_create.return_value = _openai_response(payload)
            result = classify_fingerprints(items, self.team)

        assert result == {"timed out after seconds": "timeout", "resource not found": "resource_not_found"}
        # The prompt must carry the raw message (with its numbers), not the stripped fingerprint —
        # the boundary rules pivot on codes like 429/-32601 that normalization removes.
        prompt = mock_create.call_args.kwargs["messages"][1]["content"]
        assert "timed out after 45 seconds" in prompt

    def test_batches_at_25_fingerprints(self) -> None:
        items = {f"fingerprint {i}": f"raw message {i}" for i in range(CLASSIFY_BATCH_SIZE + 1)}
        keys = list(items)
        with patch("products.mcp_analytics.backend.failure_classification.OpenAI") as mock_openai_cls:
            mock_create = mock_openai_cls.return_value.chat.completions.create
            mock_create.side_effect = [
                _openai_response(_classification_payload(keys[:CLASSIFY_BATCH_SIZE], "internal_error")),
                _openai_response(_classification_payload(keys[CLASSIFY_BATCH_SIZE:], "internal_error")),
            ]
            result = classify_fingerprints(items, self.team)

        assert mock_create.call_count == 2
        assert len(result) == len(items)

    @parameterized.expand(
        [
            ("invalid_class", [{"line_number": 1, "failure_class": "not_a_real_class"}]),
            (
                "duplicate_line_numbers",
                [{"line_number": 1, "failure_class": "timeout"}, {"line_number": 1, "failure_class": "rate_limited"}],
            ),
            ("missing_line", []),
            ("out_of_range_line", [{"line_number": 7, "failure_class": "timeout"}]),
        ]
    )
    def test_malformed_response_is_retried_then_marked_internal_error(
        self, _name: str, classifications: list[dict[str, object]]
    ) -> None:
        items = {"some fingerprint": "some raw message"}
        payload = json.dumps({"classifications": classifications})
        with patch("products.mcp_analytics.backend.failure_classification.OpenAI") as mock_openai_cls:
            mock_create = mock_openai_cls.return_value.chat.completions.create
            mock_create.side_effect = [_openai_response(payload), _openai_response(payload)]
            result = classify_fingerprints(items, self.team)

        assert mock_create.call_count == 2
        assert result == {"some fingerprint": FailureClass.INTERNAL_ERROR.value}
