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
                {"是": "yes", "否": "no", "yes": "yes", "no": "no"},
            ),
            (
                "merges_multiple_languages",
                {
                    "choices": ["yes", "no"],
                    "translations": {"zh-cn": {"choices": ["是", "否"]}, "fr": {"choices": ["oui", "non"]}},
                },
                {"是": "yes", "否": "no", "oui": "yes", "non": "no", "yes": "yes", "no": "no"},
            ),
            (
                "skips_language_when_length_is_out_of_sync",
                # A choice was removed from the base without updating the translation — positional
                # mapping would misalign, so the language is dropped entirely (base-only fallback).
                {"choices": ["yes", "no", "maybe"], "translations": {"fr": {"choices": ["oui", "non"]}}},
                {"yes": "yes", "no": "no", "maybe": "maybe"},
            ),
            (
                "seeds_base_choices_when_the_question_has_no_translations",
                # By far the common case — an untranslated choice question must still map its own
                # choices, otherwise every answer gets bucketed as <other>.
                {"choices": ["yes", "no"]},
                {"yes": "yes", "no": "no"},
            ),
            (
                "seeds_base_choices_when_translations_is_null",
                {"choices": ["yes", "no"], "translations": None},
                {"yes": "yes", "no": "no"},
            ),
            (
                "ignores_question_without_choices",
                {"question": "open ended", "translations": {"fr": {"question": "ouvert"}}},
                {},
            ),
            (
                "ignores_malformed_translation_entries",
                {"choices": ["yes", "no"], "translations": {"fr": {"choices": ["oui", 5]}}},
                {"oui": "yes", "yes": "yes", "no": "no"},
            ),
            (
                "skips_translation_needed_placeholder",
                # The editor stamps this literal into untranslated slots — it must never become a
                # key, or every language's placeholder collapses onto one arbitrary base choice.
                {"choices": ["yes", "no"], "translations": {"fr": {"choices": ["[Translation needed]", "non"]}}},
                {"non": "no", "yes": "yes", "no": "no"},
            ),
            (
                "skips_empty_and_whitespace_only_translated_choices",
                {"choices": ["yes", "no"], "translations": {"fr": {"choices": ["", "   "]}}},
                {"yes": "yes", "no": "no"},
            ),
        ]
    )
    def test_build_choice_translation_map(self, _name, question, expected):
        self.assertEqual(build_choice_translation_map(question), expected)
