from django.test import SimpleTestCase

from parameterized import parameterized

from products.replay_vision.backend.watch_feed import _reads_as_friction


class TestReadsAsFriction(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_error", "The user hit an error at checkout and retried payment twice."),
            ("gave_up", "The user couldn't find the export and gave up."),
            ("negation_turned_by_but", "No errors, but the upload failed twice."),
            ("negation_ends_at_sentence", "No issues on login. The export then crashed."),
            ("negation_ends_at_because", "The user did not finish because the form crashed."),
            ("negation_ends_at_semicolon", "No delays at first; the dashboard froze once."),
            ("bare_tag", "error"),
        ]
    )
    def test_reads_friction(self, _name: str, text: str) -> None:
        self.assertTrue(_reads_as_friction(text))

    @parameterized.expand(
        [
            ("no_term", "Checkout gone wrong"),
            ("no_before_list", "No errors or friction were observed."),
            ("no_visible", "A smooth session with no visible frustration."),
            ("without", "The user navigated without any confusion."),
            ("did_not", "The user did not struggle and saw no errors."),
            ("chained_list", "There were no errors, retries, or dead ends."),
            ("chained_after_window", "The user did not run into any errors or retries."),
            ("full_window", "The user did not see any signs of frustration."),
            ("contraction", "The user didn't appear confused at any point."),
            ("free_suffix", "The session was error-free."),
            ("zero", "Completed checkout with zero errors and no rage clicks."),
            ("negated_tag", "no-errors"),
        ]
    )
    def test_ignores_friction_it_rules_out(self, _name: str, text: str) -> None:
        self.assertFalse(_reads_as_friction(text))
