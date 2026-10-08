from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.automatic_review_rules import (
    AuthorChoice,
    AutomaticReviewDecision,
    AutomaticReviewMode,
    AutomaticReviewReason,
    RepositoryReviewRule,
)
from products.review_hog.backend.models import ReviewRepository, ReviewUserRepositoryChoice, ReviewUserSettings

YOU, TEAMMATE_A, TEAMMATE_B, TEAMMATE_C, TEAMMATE_D, TEAMMATE_E = 1, 2, 3, 4, 5, 6

EVERYONE_EXCEPT_A = RepositoryReviewRule(
    flash_for=ReviewRepository.FlashFor.EVERYONE,
    exclude_bots=True,
    listed_user_ids=frozenset({TEAMMATE_E}),
    excepted_user_ids=frozenset({TEAMMATE_A}),
)
ONLY_A_B_C = RepositoryReviewRule(
    flash_for=ReviewRepository.FlashFor.LISTED,
    exclude_bots=True,
    listed_user_ids=frozenset({TEAMMATE_A, TEAMMATE_B, TEAMMATE_C}),
    excepted_user_ids=frozenset({TEAMMATE_E}),
)
NOBODY_LISTED = RepositoryReviewRule(
    flash_for=ReviewRepository.FlashFor.LISTED,
    exclude_bots=True,
    listed_user_ids=frozenset(),
    excepted_user_ids=frozenset(),
)
EVERYONE_WITH_BOTS = RepositoryReviewRule(
    flash_for=ReviewRepository.FlashFor.EVERYONE,
    exclude_bots=False,
    listed_user_ids=frozenset(),
    excepted_user_ids=frozenset(),
)

Default = ReviewUserSettings.DefaultReviewMode
Choice = ReviewUserRepositoryChoice.Mode
Mode = AutomaticReviewMode
Reason = AutomaticReviewReason


class TestRepositoryReviewRule(SimpleTestCase):
    @parameterized.expand(
        [
            # The coverage table of the rule model: own choice > repository rule, bots excluded.
            ("you_full_everyone", EVERYONE_EXCEPT_A, YOU, Default.FULL, None, Mode.FULL, Reason.OWN_DEFAULT),
            ("you_full_listed", ONLY_A_B_C, YOU, Default.FULL, None, Mode.FULL, Reason.OWN_DEFAULT),
            ("you_full_nobody", NOBODY_LISTED, YOU, Default.FULL, None, Mode.FULL, Reason.OWN_DEFAULT),
            ("a_excepted", EVERYONE_EXCEPT_A, TEAMMATE_A, Default.FOLLOW, None, Mode.NONE, Reason.EXCEPTED),
            ("a_listed", ONLY_A_B_C, TEAMMATE_A, Default.FOLLOW, None, Mode.FLASH, Reason.LISTED),
            ("a_not_listed", NOBODY_LISTED, TEAMMATE_A, Default.FOLLOW, None, Mode.NONE, Reason.NOT_LISTED),
            ("b_flash_everyone", EVERYONE_EXCEPT_A, TEAMMATE_B, Default.FLASH, None, Mode.FLASH, Reason.OWN_DEFAULT),
            ("b_flash_listed", ONLY_A_B_C, TEAMMATE_B, Default.FLASH, None, Mode.FLASH, Reason.OWN_DEFAULT),
            ("b_flash_nobody", NOBODY_LISTED, TEAMMATE_B, Default.FLASH, None, Mode.FLASH, Reason.OWN_DEFAULT),
            ("d_off_beats_everyone", EVERYONE_EXCEPT_A, TEAMMATE_D, Default.OFF, None, Mode.NONE, Reason.OWN_DEFAULT),
            ("d_off_listed", ONLY_A_B_C, TEAMMATE_D, Default.OFF, None, Mode.NONE, Reason.OWN_DEFAULT),
            ("e_everyone", EVERYONE_EXCEPT_A, TEAMMATE_E, Default.FOLLOW, None, Mode.FLASH, Reason.EVERYONE),
            ("e_not_listed", ONLY_A_B_C, TEAMMATE_E, Default.FOLLOW, None, Mode.NONE, Reason.NOT_LISTED),
            # A per-repository choice beats the author's default, and an except list never beats it.
            (
                "a_choice_beats_except",
                EVERYONE_EXCEPT_A,
                TEAMMATE_A,
                Default.FOLLOW,
                Choice.FLASH,
                Mode.FLASH,
                Reason.OWN_REPOSITORY_CHOICE,
            ),
            (
                "b_choice_off_beats_default",
                ONLY_A_B_C,
                TEAMMATE_B,
                Default.FLASH,
                Choice.OFF,
                Mode.NONE,
                Reason.OWN_REPOSITORY_CHOICE,
            ),
            ("you_choice_full", NOBODY_LISTED, YOU, Default.OFF, Choice.FULL, Mode.FULL, Reason.OWN_REPOSITORY_CHOICE),
            # An author with no PostHog user has no own choice and is on no list.
            ("unmapped_everyone", EVERYONE_EXCEPT_A, None, Default.FOLLOW, None, Mode.FLASH, Reason.EVERYONE),
            ("unmapped_listed", ONLY_A_B_C, None, Default.FOLLOW, None, Mode.NONE, Reason.NOT_LISTED),
        ]
    )
    def test_resolve(
        self,
        _name: str,
        rule: RepositoryReviewRule,
        user_id: int | None,
        default_mode: ReviewUserSettings.DefaultReviewMode,
        repository_choice: ReviewUserRepositoryChoice.Mode | None,
        mode: AutomaticReviewMode,
        reason: AutomaticReviewReason,
    ) -> None:
        author = AuthorChoice(
            user_id=user_id, is_bot=False, default_mode=default_mode, repository_choice=repository_choice
        )

        assert rule.resolve(author) == AutomaticReviewDecision(mode=mode, reason=reason)

    @parameterized.expand(
        [
            ("excluded_everyone", EVERYONE_EXCEPT_A, Choice.FLASH, Mode.NONE, Reason.BOT_EXCLUDED),
            ("excluded_listed", ONLY_A_B_C, None, Mode.NONE, Reason.BOT_EXCLUDED),
            ("allowed_follows_the_rule", EVERYONE_WITH_BOTS, None, Mode.FLASH, Reason.EVERYONE),
        ]
    )
    def test_bot_authors(
        self,
        _name: str,
        rule: RepositoryReviewRule,
        repository_choice: ReviewUserRepositoryChoice.Mode | None,
        mode: AutomaticReviewMode,
        reason: AutomaticReviewReason,
    ) -> None:
        author = AuthorChoice(
            user_id=TEAMMATE_C, is_bot=True, default_mode=Default.FOLLOW, repository_choice=repository_choice
        )

        assert rule.resolve(author) == AutomaticReviewDecision(mode=mode, reason=reason)
