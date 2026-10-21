from datetime import date, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from pydantic import TypeAdapter

from posthog.models import Team

from products.customer_analytics.backend.facade.contracts import KeyMetric
from products.product_analytics.backend.facade.contracts import InsightSeries, InsightSeriesPending
from products.today.backend.facade import contracts
from products.today.backend.facade.contracts import PulsePin
from products.today.backend.logic import pinned, pulse_pins
from products.today.backend.logic.highlight_sources import routine
from products.today.backend.temporal.inputs import ResolvePinsInputs

TODAY = date(2026, 10, 13)
METRICS = TypeAdapter(list[contracts.HighlightMetric])
POINTS = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]


def key_metric(key: str, this_week: float, last_week: float) -> KeyMetric:
    return KeyMetric(
        key=key,
        name=key,
        people=False,
        daily=[(day, 0.0) for day, _ in POINTS],
        this_week=this_week,
        last_week=last_week,
        node={"kind": "EventsNode", "event": key},
    )


class TestPinnedNumbers(BaseTest):
    def test_saving_pins_twice_in_a_child_environment_updates_the_one_row(self) -> None:
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )

        for key in ("insight:first", "insight:second"):
            pulse_pins.set_pins(team_id=child.id, user_id=self.user.id, pins=[PulsePin(key=key, name=key)])

        self.assertEqual(
            [pin.key for pin in pulse_pins.get_pins(team_id=child.id, user_id=self.user.id)], ["insight:second"]
        )

    @parameterized.expand(
        [
            ("a cached insight", ["insight:ready"], None, [], ["insight:ready"], []),
            ("an insight whose query still runs", ["insight:slow"], None, [], [], ["insight:slow"]),
            ("a key metric with no events in either week", ["quiet"], None, [key_metric("quiet", 0, 0)], ["quiet"], []),
            ("key metrics still being calculated", ["quiet"], None, None, [], ["quiet"]),
            ("a key without insight access", ["insight:ready"], ["customer_analytics:read"], [], [], []),
        ]
    )
    def test_each_pin_is_resolved_on_its_own(
        self,
        _name: str,
        keys: list[str],
        scopes: list[str] | None,
        key_metrics: list[KeyMetric] | None,
        resolved: list[str],
        pending: list[str],
    ) -> None:
        def series(**kwargs: Any) -> InsightSeries:
            if kwargs["short_id"] == "slow":
                raise InsightSeriesPending()
            return InsightSeries(
                short_id=kwargs["short_id"],
                name=kwargs["short_id"],
                series={"opened": POINTS},
                period="day",
                averaged_series=[],
                event_name="",
            )

        with (
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(pinned, "get_key_metrics", return_value=key_metrics),
        ):
            result = pinned.resolve_pins(
                ResolvePinsInputs(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    local_day=TODAY.isoformat(),
                    scopes=scopes,
                    keys=keys,
                )
            )

        self.assertEqual(
            ([metric.key for metric in METRICS.validate_json(result.found)], result.pending, result.failed),
            (resolved, pending, False),
        )
