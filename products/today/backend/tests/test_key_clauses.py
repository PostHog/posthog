from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.facade.contracts import KeyClauseRequest, TextKeyClauses
from products.today.backend.facade.enums import KeyClauseRole
from products.today.backend.logic.code_excerpts import which_excerpt
from products.today.backend.logic.jev import JevPick
from products.today.backend.logic.key_clauses import find_key_clauses, text_clauses

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


class FakeJev:
    def __init__(self, texts: list[str], roles: dict[str, JevPick], explanations: dict[str, str]) -> None:
        self.texts = texts
        self.roles = roles
        self.explanations = explanations

    def _marked_part(self, item: str) -> str:
        part = item
        for text in self.texts:
            part = part.replace(text, "")
        return next((clause for clause in self.roles if clause in part), "")

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        return [self.roles.get(self._marked_part(item)) for item in items]

    def yes(self, items: list[str], question: str) -> list[float | None]:
        return [
            0.9 if any(clause in item and sentence in item for clause, sentence in self.explanations.items()) else 0.1
            for item in items
        ]


def shown(found: list[TextKeyClauses]) -> dict[str, list[tuple[str, list[str]]]]:
    return {texts.text: [(clause.text, clause.expansion) for clause in texts.key_clauses] for texts in found}


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
        found = find_key_clauses(
            [KeyClauseRequest(text=CART_TEXT, roles=PROBLEM_AND_CAUSE)],
            SUMMARY,
            FakeJev([CART_TEXT], roles, explanations),
        )
        assert shown(found) == {CART_TEXT: expected}

    def test_gives_each_text_its_own_clauses_and_at_most_two_across_all_texts(self) -> None:
        found = find_key_clauses(
            [
                KeyClauseRequest(text=CART_TEXT, roles=PROBLEM_AND_CAUSE),
                KeyClauseRequest(text=FIX_TEXT, roles=[KeyClauseRole.FIX]),
            ],
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
        assert shown(found) == {
            CART_TEXT: [(FROZEN_SPINNER, [SPINNER_EXPLAINED])],
            FIX_TEXT: [(FIX, [FIX_EXPLAINED])],
        }

    @parameterized.expand(
        [
            ("a sure pick", JevPick(label="2", probability=0.8), 1),
            ("an unsure pick", JevPick(label="2", probability=0.4), None),
            ("no pick", None, None),
        ]
    )
    def test_picks_the_excerpt_a_finding_describes(
        self, _name: str, pick: JevPick | None, expected: int | None
    ) -> None:
        jev = FakeJev([], {}, {})
        jev.choice = lambda items, question, labels: [pick]  # type: ignore[method-assign]
        assert which_excerpt("The cart drops the token.", ["a = 1", "drop(token)"], jev) == expected
