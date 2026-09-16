from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.scout_naming import fallback_scout_slug, slugify_scout_name
from products.skills.backend.api.skill_serializers import validate_skill_name_value
from products.skills.backend.api.skill_services import MAX_SKILL_NAME_LENGTH


class TestSlugifyScoutName(SimpleTestCase):
    @parameterized.expand(
        [
            ("spaces and acronyms", "My APM scout", "my-apm-scout"),
            ("punctuation between words", "Checkout / daily digest", "checkout-daily-digest"),
            ("underscores are word separators", "checkout_failed watch", "checkout-failed-watch"),
            ("accents transliterate", "Café latency", "cafe-latency"),
            ("surrounding whitespace", "  Checkout failures  ", "checkout-failures"),
            ("leading and trailing punctuation", "-- Checkout! --", "checkout"),
            ("punctuation only", "!!! ???", ""),
            ("script that does not transliterate", "監視", ""),
        ]
    )
    def test_slug_for(self, _name: str, display_name: str, expected: str) -> None:
        assert slugify_scout_name(display_name) == expected

    @parameterized.expand(
        [
            ("an ordinary name", "My APM scout"),
            ("a name far past the cap", "Checkout failures " * 20),
            ("a name whose cut lands on a word boundary", "a" * (MAX_SKILL_NAME_LENGTH - 1) + " tail"),
        ]
    )
    def test_slug_is_a_usable_skill_name(self, _name: str, display_name: str) -> None:
        # Every slug is stored as an LLMSkill name, so one the skill contract refuses is a create
        # that fails on a name the user never chose — a trailing hyphen left by the length cut is
        # the way that happens.
        validate_skill_name_value(slugify_scout_name(display_name))

    def test_fallback_slug_is_a_usable_skill_name(self) -> None:
        validate_skill_name_value(fallback_scout_slug())
