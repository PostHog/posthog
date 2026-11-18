from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.scout_naming import (
    _slug_candidates,
    allocate_scout_slug,
    fallback_scout_slug,
    slugify_scout_name,
)
from products.skills.backend.api.skill_serializers import validate_skill_name_value
from products.skills.backend.api.skill_services import MAX_SKILL_NAME_LENGTH
from products.skills.backend.models.skills import LLMSkill


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


class TestAllocateScoutSlug(BaseTest):
    def _allocate(self, display_name: str) -> str:
        return allocate_scout_slug(team_id=self.team.id, display_name=display_name)

    def test_suffixes_past_every_slug_the_team_already_holds(self) -> None:
        LLMSkill.objects.create(team=self.team, name="checkout-failures", description="d", body="b")
        SignalScoutConfig.objects.create(team=self.team, skill_name="checkout-failures-2")

        assert self._allocate("Checkout failures") == "checkout-failures-3"

    def test_finds_a_suffixed_slug_whose_base_was_cut_to_fit(self) -> None:
        # A base that fills the name cap loses its last characters to make room for the suffix, so
        # the taken slug does not start with the base. Matching on the base as a prefix misses it
        # and hands back a name another scout already holds.
        display_name = "a" * MAX_SKILL_NAME_LENGTH
        taken = f"{'a' * (MAX_SKILL_NAME_LENGTH - 2)}-2"
        SignalScoutConfig.objects.create(team=self.team, skill_name="a" * MAX_SKILL_NAME_LENGTH)
        SignalScoutConfig.objects.create(team=self.team, skill_name=taken)

        allocated = self._allocate(display_name)

        assert allocated != taken
        validate_skill_name_value(allocated)

    def test_falls_back_once_the_suffixes_run_out(self) -> None:
        # A generated slug is never reported as free when it is taken, however many are: the
        # caller creates under whatever comes back, so a wrong answer attaches to another scout.
        for name in _slug_candidates("checkout-failures"):
            SignalScoutConfig.objects.create(team=self.team, skill_name=name)

        allocated = self._allocate("Checkout failures")

        assert allocated.startswith("scout-")
        validate_skill_name_value(allocated)

    def test_holds_back_the_slugs_a_concurrent_create_already_won(self) -> None:
        assert (
            allocate_scout_slug(team_id=self.team.id, display_name="Checkout failures", taken={"checkout-failures"})
            == "checkout-failures-2"
        )

    def test_another_teams_slug_is_not_reserved(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")
        SignalScoutConfig.objects.create(team=other, skill_name="checkout-failures")

        assert self._allocate("Checkout failures") == "checkout-failures"
