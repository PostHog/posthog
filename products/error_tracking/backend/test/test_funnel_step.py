from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.funnel_step import (
    StepChange,
    find_broken_step,
    find_chain_drop_hours,
)
from products.error_tracking.backend.logic.recommendations.page_flows import (
    Chain,
    EvaluationWindow,
    Flow,
    StepCounts,
    pick_chains,
)

HOUR = datetime(2026, 1, 15, 9, tzinfo=UTC)
WINDOW = EvaluationWindow(first_hour=HOUR - timedelta(hours=6), last_hour=HOUR)


def _flows(*steps: str) -> list[Flow]:
    return [Flow(from_path=step[0], to_path=step[1]) for step in steps]


class TestPickChains(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_flow_is_not_a_chain", ["ab"], []),
            ("two_linked_flows", ["ab", "bc"], ["abc"]),
            # The three-page chains inside a four-page chain are covered by its steps.
            ("longest_chain_only", ["ab", "bc", "cd"], ["abcd"]),
            ("at_most_four_pages", ["ab", "bc", "cd", "de"], ["abcd", "bcde"]),
            ("a_page_with_two_next_pages", ["ab", "bc", "bd"], ["abc", "abd"]),
            # Going round the loop would visit the first page again.
            ("never_revisits_a_page", ["ab", "bc", "ca"], ["abc", "bca", "cab"]),
        ]
    )
    def test_links_flows_where_one_ends_on_the_page_the_next_starts(
        self, _name: str, steps: list[str], chains: list[str]
    ) -> None:
        self.assertEqual(pick_chains(_flows(*steps)), [Chain(pages=tuple(chain)) for chain in chains])


class TestFindChainDropHours(SimpleTestCase):
    @parameterized.expand(
        [
            # name, usual (starts, finishes) on 4 previous days, current (starts, finishes), dropped
            # 10% to 3% is 7 points, under Broken flow's 8-point bar, but far below usual for a chain.
            ("low_rate_falls_far_below_usual", (60, 6), (600, 18), True),
            ("same_fall_under_four_standard_errors", (60, 6), (250, 8), False),
            ("rate_above_seven_tenths_of_usual", (60, 18), (250, 60), False),
            ("too_few_starts", (60, 18), (199, 0), False),
        ]
    )
    def test_flags_hours_far_below_the_usual_rate_of_the_whole_chain(
        self, _name: str, usual: tuple[int, int], current: tuple[int, int], dropped: bool
    ) -> None:
        hours = {HOUR - timedelta(days=days): StepCounts(reached=(usual[0], 40, usual[1])) for days in range(1, 5)}
        hours[HOUR] = StepCounts(reached=(current[0], 100, current[1]))

        self.assertEqual(find_chain_drop_hours(hours, WINDOW), [HOUR] if dropped else [])


class TestFindBrokenStep(SimpleTestCase):
    @parameterized.expand(
        [
            # name, each step's (entered, continued, usual rate), broken step, clear
            ("one_step_fell_and_the_others_held", [(300, 180, 0.6), (180, 18, 0.5)], 1, True),
            ("two_steps_fell", [(300, 120, 0.6), (120, 12, 0.5)], 1, False),
            ("lowest_step_fell_only_a_little", [(300, 165, 0.6), (165, 70, 0.5)], 1, False),
            # A step with too few visits entering it cannot be judged, so it neither breaks nor holds.
            ("step_with_too_few_entrants", [(300, 15, 0.6), (15, 0, 0.5)], 0, True),
            ("step_without_a_usual_rate", [(300, 180, None), (180, 18, 0.5)], 1, True),
            ("no_step_can_be_judged", [(300, 180, None), (20, 2, 0.5)], None, False),
        ]
    )
    def test_names_the_step_furthest_below_its_usual_rate(
        self,
        _name: str,
        steps: list[tuple[int, int, float | None]],
        index: int | None,
        clear: bool,
    ) -> None:
        changes = [
            StepChange(flow=Flow(from_path=f"/{step}", to_path=f"/{step + 1}"), entered=e, continued=c, usual_rate=u)
            for step, (e, c, u) in enumerate(steps)
        ]

        broken = find_broken_step(changes)

        self.assertEqual((broken.index, broken.clear) if broken else (None, False), (index, clear))
