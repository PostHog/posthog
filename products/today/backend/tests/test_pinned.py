from datetime import date, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from pydantic import TypeAdapter

from posthog.models import Team

from products.customer_analytics.backend.facade.contracts import KeyMetric
from products.dashboards.backend.facade.api import DashboardInsights, DashboardInsightTile
from products.product_analytics.backend.facade.contracts import InsightSeries, InsightSeriesPending
from products.today.backend.facade import contracts
from products.today.backend.facade.contracts import PulsePin
from products.today.backend.logic import pinned, pulse_pins
from products.today.backend.logic.highlight_sources import routine
from products.today.backend.temporal.inputs import PinnedNumber, ResolvePinsInputs

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
            ("a cached insight", [PinnedNumber("insight:ready")], None, [], [("insight:ready", None)], [], False),
            (
                "an insight whose query still runs",
                [PinnedNumber("insight:slow")],
                None,
                [],
                [],
                ["insight:slow"],
                False,
            ),
            ("an insight whose query fails", [PinnedNumber("insight:broken")], None, [], [], [], True),
            (
                "a tile pinned from a dashboard",
                [PinnedNumber("insight:ready", dashboard_id=7)],
                None,
                [],
                [("insight:ready", "/dashboard/7")],
                [],
                False,
            ),
            (
                "a tile removed from its dashboard",
                [PinnedNumber("insight:ready", dashboard_id=8)],
                None,
                [],
                [],
                [],
                False,
            ),
            (
                "a key metric with no events in either week",
                [PinnedNumber("quiet")],
                None,
                [key_metric("quiet", 0, 0)],
                [("quiet", None)],
                [],
                False,
            ),
            ("key metrics still being calculated", [PinnedNumber("quiet")], None, None, [], ["quiet"], False),
            (
                "a key without insight access",
                [PinnedNumber("insight:ready")],
                ["customer_analytics:read"],
                [],
                [],
                [],
                False,
            ),
        ]
    )
    def test_each_pin_is_resolved_on_its_own(
        self,
        _name: str,
        pins: list[PinnedNumber],
        scopes: list[str] | None,
        key_metrics: list[KeyMetric] | None,
        resolved: list[tuple[str, str | None]],
        pending: list[str],
        failed: bool,
    ) -> None:
        def series(**kwargs: Any) -> InsightSeries:
            if kwargs["short_id"] == "slow":
                raise InsightSeriesPending()
            if kwargs["short_id"] == "broken":
                raise ValueError("query failed")
            return InsightSeries(
                short_id=kwargs["short_id"],
                name=kwargs["short_id"],
                series={"opened": POINTS},
                period="day",
                averaged_series=[],
                event_name="",
            )

        growth = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(DashboardInsightTile(insight_short_id="ready", filters_overrides=None),),
        )

        def tile(**kwargs: Any) -> DashboardInsights | None:
            return growth if kwargs["dashboard_id"] == 7 else None

        with (
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(routine, "dashboard_insight_tile", side_effect=tile),
            patch.object(pinned, "get_key_metrics", return_value=key_metrics),
        ):
            result = pinned.resolve_pins(
                ResolvePinsInputs(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    local_day=TODAY.isoformat(),
                    scopes=scopes,
                    pins=pins,
                )
            )

        self.assertEqual(
            (
                [
                    (metric.key, metric.url if metric.dashboard_id else None)
                    for metric in METRICS.validate_json(result.found)
                ],
                result.pending,
                result.failed,
            ),
            (resolved, pending, failed),
        )
