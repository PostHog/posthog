"""Unit tests for the pure helpers in fetch_rows (no ClickHouse needed)."""

from django.test import SimpleTestCase

from parameterized import parameterized

from products.surveys.backend.responses.fetch_rows import build_choice_translation_map


class TestBuildChoiceTranslationMap(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "maps_each_translation_back_to_its_base_choice",
                {"choices": ["yes", "no"], "translations": {"zh-cn": {"choices": ["是", "否"]}}},
                {"是": "yes", "否": "no"},
            ),
            (
                "merges_multiple_languages",
                {
                    "choices": ["yes", "no"],
                    "translations": {"zh-cn": {"choices": ["是", "否"]}, "fr": {"choices": ["oui", "non"]}},
                },
                {"是": "yes", "否": "no", "oui": "yes", "non": "no"},
            ),
            (
                "skips_language_when_length_is_out_of_sync",
                # A choice was removed from the base without updating the translation — positional
                # mapping would misalign, so the language is dropped entirely (base-only fallback).
                {"choices": ["yes", "no", "maybe"], "translations": {"fr": {"choices": ["oui", "non"]}}},
                {},
            ),
            (
                "ignores_question_without_choices",
                {"question": "open ended", "translations": {"fr": {"question": "ouvert"}}},
                {},
            ),
            (
                "ignores_malformed_translation_entries",
                {"choices": ["yes", "no"], "translations": {"fr": {"choices": ["oui", 5]}}},
                {"oui": "yes"},
            ),
        ]
    )
    def test_build_choice_translation_map(self, _name, question, expected):
        self.assertEqual(build_choice_translation_map(question), expected)

    def test_does_not_seed_base_choices(self):
        # Base choices are folded in by the consumer (per_question_stats), not here, so a
        # collision-safe seeding order can be enforced downstream.
        question = {"choices": ["yes", "no"], "translations": {"fr": {"choices": ["oui", "non"]}}}
        result = build_choice_translation_map(question)
        self.assertNotIn("yes", result)
        self.assertNotIn("no", result)
