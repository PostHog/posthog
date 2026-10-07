from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.code_excerpts import which_excerpt
from products.today.backend.logic.jev import JevPick
from products.today.backend.tests.factories import PickJev


class TestCodeExcerpts(SimpleTestCase):
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
        assert which_excerpt("The cart drops the token.", ["a = 1", "drop(token)"], PickJev(pick)) == expected
