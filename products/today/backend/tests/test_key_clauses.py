from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.facade.contracts import KeyClause
from products.today.backend.facade.enums import KeyClauseRole
from products.today.backend.logic.jev import JevPick
from products.today.backend.logic.key_clauses import KeyClauseRequest, find_key_clauses, text_clauses
from products.today.backend.tests.factories import FakeJev

CART_TEXT = "Shoppers see an empty cart, a frozen spinner, and a blank receipt because the cart service drops the session token."
FIX_TEXT = "Keep the token in a cookie so the cart survives the switch."
CART_EXPLAINED = "The cart page renders before the session loads and shows zero items."
SPINNER_EXPLAINED = "The spinner waits on a price request that never returns."
CAUSE_EXPLAINED = "The service drops the token when a shopper moves from the app to the browser."
FIX_EXPLAINED = "A cookie keeps the token across that move for one extra header."
SUMMARY = "\n\n".join([CART_TEXT, FIX_TEXT, CART_EXPLAINED, SPINNER_EXPLAINED, CAUSE_EXPLAINED, FIX_EXPLAINED])
EMPTY_CART = "Shoppers see an empty cart"
FROZEN_SPINNER = "a frozen spinner"
CAUSE = "because the cart service drops the session token"
FIX = "Keep the token in a cookie"


def shown(requests: list[KeyClauseRequest], found: list[list[KeyClause]]) -> dict[str, list[tuple[str, list[str]]]]:
    return {
        request.text: [(request.text[clause.start : clause.end], clause.expansion) for clause in own]
        for request, own in zip(requests, found)
    }


PROBLEM_AND_CAUSE = [KeyClauseRole.PROBLEM, KeyClauseRole.CAUSE]


class TestKeyClauses(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "punctuation and a word that opens a clause",
                "Shoppers on the mobile app see an empty cart, a frozen spinner, and a blank receipt because the cart service drops the session token.",
                [
                    "Shoppers on the mobile app see an empty cart",
                    "a frozen spinner",
                    "and a blank receipt",
                    "because the cart service drops the session token",
                ],
            ),
            (
                "file names and an uppercase OR kept whole",
                "The filter in orders_view.ts joins carts across an OR, so each query scans every row.",
                ["The filter in orders_view.ts joins carts across an OR", "so each query scans every row"],
            ),
            (
                "a dash between clauses but not inside a number range",
                "Checkout fails for 120–150 shoppers a week – the coupon step drops their cart.",
                ["Checkout fails for 120–150 shoppers a week", "the coupon step drops their cart"],
            ),
            (
                "one sentence across a period when the next word is lowercase",
                "The work is already in flight. #1192 shows the cart on narrow windows, and 1,204 shoppers use it.",
                ["The work is already in flight. #1192 shows the cart on narrow windows", "and 1,204 shoppers use it"],
            ),
        ]
    )
    def test_splits_text_into_clauses(self, _name: str, text: str, expected: list[str]) -> None:
        assert [clause.text for clause in text_clauses(text)] == expected

    @parameterized.expand(
        [
            (
                "the surest clause for each role",
                {
                    EMPTY_CART: JevPick(label="problem", probability=0.8),
                    FROZEN_SPINNER: JevPick(label="problem", probability=0.9),
                    CAUSE: JevPick(label="cause", probability=0.85),
                },
                {EMPTY_CART: CART_EXPLAINED, FROZEN_SPINNER: SPINNER_EXPLAINED, CAUSE: CAUSE_EXPLAINED},
                [(FROZEN_SPINNER, [SPINNER_EXPLAINED]), (CAUSE, [CAUSE_EXPLAINED])],
            ),
            (
                "a less sure clause the report explains, over a surer one it does not",
                {
                    FROZEN_SPINNER: JevPick(label="problem", probability=0.95),
                    EMPTY_CART: JevPick(label="problem", probability=0.8),
                },
                {EMPTY_CART: CART_EXPLAINED},
                [(EMPTY_CART, [CART_EXPLAINED])],
            ),
            (
                "only a clause the report explains",
                {
                    FROZEN_SPINNER: JevPick(label="problem", probability=0.95),
                    CAUSE: JevPick(label="cause", probability=0.8),
                },
                {CAUSE: CAUSE_EXPLAINED},
                [(CAUSE, [CAUSE_EXPLAINED])],
            ),
            (
                "nothing for an unsure role",
                {
                    FROZEN_SPINNER: JevPick(label="problem", probability=0.7),
                    CAUSE: JevPick(label="cause", probability=0.7),
                },
                {FROZEN_SPINNER: SPINNER_EXPLAINED, CAUSE: CAUSE_EXPLAINED},
                [],
            ),
        ]
    )
    def test_shows(
        self,
        _name: str,
        roles: dict[str, JevPick],
        explanations: dict[str, str],
        expected: list[tuple[str, list[str]]],
    ) -> None:
        requests = [KeyClauseRequest(text=CART_TEXT, roles=PROBLEM_AND_CAUSE)]
        found = find_key_clauses(requests, SUMMARY, FakeJev([CART_TEXT], roles, explanations))
        assert shown(requests, found) == {CART_TEXT: expected}

    def test_gives_each_text_its_own_clauses_and_at_most_two_across_all_texts(self) -> None:
        requests = [
            KeyClauseRequest(text=CART_TEXT, roles=PROBLEM_AND_CAUSE),
            KeyClauseRequest(text=FIX_TEXT, roles=[KeyClauseRole.FIX]),
        ]
        found = find_key_clauses(
            requests,
            SUMMARY,
            FakeJev(
                [CART_TEXT, FIX_TEXT],
                {
                    FROZEN_SPINNER: JevPick(label="problem", probability=0.95),
                    CAUSE: JevPick(label="cause", probability=0.8),
                    FIX: JevPick(label="fix", probability=0.9),
                },
                {FROZEN_SPINNER: SPINNER_EXPLAINED, CAUSE: CAUSE_EXPLAINED, FIX: FIX_EXPLAINED},
            ),
        )
        assert shown(requests, found) == {
            CART_TEXT: [(FROZEN_SPINNER, [SPINNER_EXPLAINED])],
            FIX_TEXT: [(FIX, [FIX_EXPLAINED])],
        }

    def test_places_clauses_by_the_offsets_the_browser_counts(self) -> None:
        text = f"🛒 {CART_TEXT}"
        [clauses] = find_key_clauses(
            [KeyClauseRequest(text=text, roles=[KeyClauseRole.CAUSE])],
            SUMMARY,
            FakeJev([text], {CAUSE: JevPick(label="cause", probability=0.9)}, {CAUSE: CAUSE_EXPLAINED}),
        )
        [clause] = clauses
        assert (clause.start, clause.end) == (text.index(CAUSE) + 1, text.index(CAUSE) + 1 + len(CAUSE))
