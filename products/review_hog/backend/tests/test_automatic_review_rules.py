from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.automatic_review_rules import (
    AuthorChoice,
    AutomaticReviewDecision,
    AutomaticReviewReason,
    AutomaticReviewRule,
    FlashRule,
)
from products.review_hog.backend.models import AutomaticFlashFor, ReviewUserRepositoryChoice
from products.review_hog.backend.preferences import DefaultReviewMode

YOU, TEAMMATE_A, TEAMMATE_B, TEAMMATE_C = 1, 2, 3, 4

EVERYONE_EXCEPT_A = FlashRule(
    flash_for=AutomaticFlashFor.EVERYONE,
    listed_user_ids=frozenset({TEAMMATE_C}),
    excepted_user_ids=frozenset({TEAMMATE_A}),
)
ONLY_A_B = FlashRule(
    flash_for=AutomaticFlashFor.LISTED,
    listed_user_ids=frozenset({TEAMMATE_A, TEAMMATE_B}),
    excepted_user_ids=frozenset({TEAMMATE_C}),
)
EVERYONE_NO_LISTS = FlashRule(
    flash_for=AutomaticFlashFor.EVERYONE, listed_user_ids=frozenset(), excepted_user_ids=frozenset()
)
OPT_IN_ONLY = FlashRule(flash_for=AutomaticFlashFor.OFF, listed_user_ids=frozenset(), excepted_user_ids=frozenset())

Default = DefaultReviewMode
Choice = ReviewUserRepositoryChoice.Mode
Reason = AutomaticReviewReason


def rule(project: FlashRule, repository: FlashRule | None = None, *, review_bots: bool = False) -> AutomaticReviewRule:
    return AutomaticReviewRule(project=project, repository=repository, review_bots=review_bots)


class TestAutomaticReviewRule(SimpleTestCase):
    @parameterized.expand(
        [
            ("project_everyone", rule(EVERYONE_EXCEPT_A), YOU, Default.FOLLOW, None, True, Reason.PROJECT_EVERYONE),
            (
                "project_excepted",
                rule(EVERYONE_EXCEPT_A),
                TEAMMATE_A,
                Default.FOLLOW,
                None,
                False,
                Reason.PROJECT_EXCEPTED,
            ),
            ("project_listed", rule(ONLY_A_B), TEAMMATE_A, Default.FOLLOW, None, True, Reason.PROJECT_LISTED),
            ("project_not_listed", rule(ONLY_A_B), YOU, Default.FOLLOW, None, False, Reason.PROJECT_NOT_LISTED),
            ("project_opt_in", rule(OPT_IN_ONLY), YOU, Default.FOLLOW, None, False, Reason.PROJECT_OPT_IN),
            # A repository exception replaces the project rule, lists included.
            (
                "exception_beats_project",
                rule(EVERYONE_EXCEPT_A, OPT_IN_ONLY),
                YOU,
                Default.FOLLOW,
                None,
                False,
                Reason.REPOSITORY_OPT_IN,
            ),
            (
                "exception_lists_not_project_lists",
                rule(EVERYONE_EXCEPT_A, EVERYONE_NO_LISTS),
                TEAMMATE_A,
                Default.FOLLOW,
                None,
                True,
                Reason.REPOSITORY_EVERYONE,
            ),
            (
                "exception_listed",
                rule(OPT_IN_ONLY, ONLY_A_B),
                TEAMMATE_B,
                Default.FOLLOW,
                None,
                True,
                Reason.REPOSITORY_LISTED,
            ),
            # The author's default beats the repository exception and the project rule.
            ("default_flash", rule(OPT_IN_ONLY, OPT_IN_ONLY), YOU, Default.FLASH, None, True, Reason.OWN_DEFAULT),
            (
                "default_off",
                rule(EVERYONE_EXCEPT_A, EVERYONE_EXCEPT_A),
                YOU,
                Default.OFF,
                None,
                False,
                Reason.OWN_DEFAULT,
            ),
            # The author's repository choice beats everything else.
            (
                "choice_beats_default",
                rule(EVERYONE_EXCEPT_A),
                YOU,
                Default.OFF,
                Choice.FLASH,
                True,
                Reason.OWN_REPOSITORY_CHOICE,
            ),
            (
                "choice_beats_except_list",
                rule(EVERYONE_EXCEPT_A),
                TEAMMATE_A,
                Default.FOLLOW,
                Choice.FLASH,
                True,
                Reason.OWN_REPOSITORY_CHOICE,
            ),
            (
                "choice_off",
                rule(EVERYONE_EXCEPT_A),
                YOU,
                Default.FLASH,
                Choice.OFF,
                False,
                Reason.OWN_REPOSITORY_CHOICE,
            ),
        ]
    )
    def test_resolve_for_members(
        self,
        _name: str,
        automatic_rule: AutomaticReviewRule,
        user_id: int,
        default_mode: DefaultReviewMode,
        repository_choice: ReviewUserRepositoryChoice.Mode | None,
        flash: bool,
        reason: AutomaticReviewReason,
    ) -> None:
        author = AuthorChoice(
            user_id=user_id, is_bot=False, default_mode=default_mode, repository_choice=repository_choice
        )

        assert automatic_rule.resolve(author) == AutomaticReviewDecision(flash=flash, reason=reason)

    @parameterized.expand(
        [
            ("bot_skipped", True, TEAMMATE_C, False, False, Reason.BOT_SKIPPED),
            ("bot_reviewed_even_when_excepted", True, TEAMMATE_A, True, True, Reason.BOT_REVIEWED),
            ("unmapped_skipped", False, None, False, False, Reason.BOT_SKIPPED),
            ("unmapped_reviewed", False, None, True, True, Reason.BOT_REVIEWED),
        ]
    )
    def test_bots_and_unmapped_authors_follow_the_bot_rule(
        self,
        _name: str,
        is_bot: bool,
        user_id: int | None,
        review_bots: bool,
        flash: bool,
        reason: AutomaticReviewReason,
    ) -> None:
        author = AuthorChoice(user_id=user_id, is_bot=is_bot, default_mode=Default.FOLLOW, repository_choice=None)

        decision = rule(EVERYONE_EXCEPT_A, review_bots=review_bots).resolve(author)

        assert decision == AutomaticReviewDecision(flash=flash, reason=reason)
