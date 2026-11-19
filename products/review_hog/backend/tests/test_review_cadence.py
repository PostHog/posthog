from itertools import product

from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.review_cadence import ReviewCadence

# Events after the first automatic review: (webhook action, draft state the last automatic review saw, draft now).
_EVENTS = {
    "push_to_a_reviewed_draft": ("synchronize", True, True),
    "reviewed_draft_marked_ready": ("ready_for_review", True, False),
    "push_after_the_ready_review": ("synchronize", False, False),
    "marked_ready_again_after_the_ready_review": ("ready_for_review", False, False),
}

# (review_drafts, review_pushes) -> the events that get a turn. The push gate's own rules still judge
# each turn, so a push to a draft that passes here is skipped by the draft rule.
_EXPECTED_TURNS = {
    (False, False): {"reviewed_draft_marked_ready"},
    (False, True): set(_EVENTS),
    (True, False): {"reviewed_draft_marked_ready"},
    (True, True): set(_EVENTS),
}


class TestReviewCadence(SimpleTestCase):
    @parameterized.expand(
        [
            (f"drafts_{drafts}_pushes_{pushes}_{event}", drafts, pushes, event)
            for (drafts, pushes), event in product(_EXPECTED_TURNS, _EVENTS)
        ]
    )
    def test_follow_up_turns_match_the_cadence_table(self, _name: str, drafts: bool, pushes: bool, event: str) -> None:
        cadence = ReviewCadence(review_drafts=drafts, review_pushes=pushes)
        action, reviewed_draft, draft = _EVENTS[event]

        runs = cadence.dispatches_follow_up(action) and cadence.allows_follow_up(
            reviewed_draft=reviewed_draft, draft=draft
        )

        assert runs == (event in _EXPECTED_TURNS[(drafts, pushes)])

    @parameterized.expand(
        [
            ("queued_while_the_draft_review_ran", True, True, False),
            ("draft_state_unknown_now", True, None, True),
            ("draft_state_of_the_last_review_unknown", None, False, False),
        ]
    )
    def test_without_push_reviews_only_a_ready_pr_after_a_draft_review_gets_a_turn(
        self, _name: str, reviewed_draft: bool | None, draft: bool | None, expected: bool
    ) -> None:
        cadence = ReviewCadence(review_drafts=True, review_pushes=False)

        assert cadence.allows_follow_up(reviewed_draft=reviewed_draft, draft=draft) is expected

    @parameterized.expand([(True, True, True), (True, False, False), (False, True, False)])
    def test_an_opening_draft_needs_the_repository_and_the_author(
        self, repository_on: bool, author_allows: bool, expected: bool
    ) -> None:
        cadence = ReviewCadence(review_drafts=repository_on, review_pushes=False)

        assert cadence.reviews_opening_draft(author_allows=author_allows) is expected
