import json
from datetime import date, timedelta
from itertools import count
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import unquote

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.facade.contracts import KeyMetric
from products.today.backend.facade.contracts import PulseSlot
from products.today.backend.facade.enums import PulseSlotStatus
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_types import Context, DailyValueNotReady
from products.today.backend.logic.today_highlights import key_metrics

TODAY = date(2026, 10, 13)


def metric(key: str, values: list[float], *, people: bool = False) -> KeyMetric:
    start = TODAY - timedelta(days=len(values))
    daily = [(start + timedelta(days=i), v) for i, v in enumerate(values)]
    return KeyMetric(
        key=key,
        name=key.replace("_", " ").capitalize(),
        people=people,
        daily=daily,
        this_week=sum(values[-7:]),
        last_week=sum(values[-14:-7]),
        node={"kind": "EventsNode", "event": key},
    )


def _query(url: str | None) -> Any:
    assert url is not None and url.startswith("/insights/new#q=")
    return json.loads(unquote(url.removeprefix("/insights/new#q=")))


def _trend(series: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [series],
            "interval": "day",
            "dateRange": {"date_from": "2026-09-15", "date_to": "2026-10-12"},
            "filterTestAccounts": True,
        },
    }


class TestKeyMetrics(SimpleTestCase):
    @parameterized.expand([("nothing_hidden", frozenset()), ("a_hidden_metric", frozenset({"activity_event"}))])
    def test_key_metrics_fill_the_pulse_and_a_weekday_drop_becomes_an_item(
        self, _name: str, hidden: frozenset[str]
    ) -> None:
        drop = [1000.0] * 6 + [1010.0] + [1000.0] * 6 + [990.0] + [1000.0] * 20 + [500.0]
        metrics = [
            metric("signup_event", drop),
            metric("payment_event", [0.0] * 35),
            metric("activity_event", [20.0] * 35, people=True),
        ]
        context = cast(
            Context,
            SimpleNamespace(
                team=SimpleNamespace(id=1),
                user=SimpleNamespace(id=2),
                today=TODAY,
                hidden=hidden,
                publish_pulse=lambda found, slots: None,
            ),
        )
        registered = next(s for s in load_sources() if s.name == "key_metrics")

        with (
            patch.object(key_metrics, "get_key_metric_names", return_value={}),
            patch.object(key_metrics, "get_key_metrics", return_value=metrics),
        ):
            found = registered.find(context)

        self.assertEqual(
            (
                [(m.key, m.value, m.unit, m.change_pct, m.previous_value, len(m.series)) for m in found.pulse],
                [(c.title, c.detail, c.label) for c in found.items],
                [_query(m.url) for m in found.pulse],
            ),
            (
                [
                    tile
                    for tile in (
                        ("signup_event", 6500.0, "events", -7.1, 7000.0, 28),
                        ("activity_event", 140.0, "people", 0.0, 140.0, 28),
                    )
                    if tile[0] not in hidden
                ],
                [("‘Signup event’ decreased by 50% yesterday", "500 yesterday · 1,000 on an average Monday", "risk")],
                [
                    query
                    for key, query in (
                        ("signup_event", _trend({"kind": "EventsNode", "event": "signup_event", "math": "total"})),
                        ("activity_event", _trend({"kind": "EventsNode", "event": "activity_event", "math": "dau"})),
                    )
                    if key not in hidden
                ],
            ),
        )

    def test_a_pending_calculation_asks_for_a_quick_retry(self) -> None:
        published: list[list[PulseSlot]] = []
        context = cast(
            Context,
            SimpleNamespace(
                team=SimpleNamespace(id=1),
                user=SimpleNamespace(id=2),
                today=TODAY,
                hidden=frozenset(),
                publish_pulse=lambda found, slots: published.append(slots),
            ),
        )
        registered = next(s for s in load_sources() if s.name == "key_metrics")

        with (
            patch.object(key_metrics, "get_key_metric_names", return_value={"signup_event": "Sign-ups"}),
            patch.object(key_metrics, "get_key_metrics", return_value=None),
            patch.object(key_metrics, "monotonic", side_effect=count(0, 30)),
            patch.object(key_metrics, "sleep"),
            self.assertRaises(DailyValueNotReady),
        ):
            registered.find(context)

        self.assertEqual([slot.status for slot in published[-1]], [PulseSlotStatus.ERROR])
