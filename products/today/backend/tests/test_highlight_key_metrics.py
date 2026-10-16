from datetime import date, timedelta
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

from products.customer_analytics.backend.facade.contracts import KeyMetric
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import key_metrics
from products.today.backend.logic.highlight_types import Context

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
    )


class TestKeyMetrics(SimpleTestCase):
    def test_key_metrics_fill_the_pulse_and_a_weekday_drop_becomes_an_item(self) -> None:
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
                daily=lambda _name, compute: compute(),
            ),
        )
        registered = next(s for s in load_sources() if s.name == "key_metrics")

        with (
            patch.object(key_metrics, "get_key_metrics", return_value=metrics),
            patch.object(key_metrics, "get_key_metrics_fingerprint", return_value="config"),
        ):
            found = registered.find(context)

        self.assertEqual(
            (
                [(m.key, m.value, m.unit, m.change_pct, len(m.series)) for m in found.pulse],
                [(c.title, c.detail, c.label) for c in found.items],
            ),
            (
                [("signup_event", 6500.0, "events", -7.1, 28), ("activity_event", 140.0, "people", 0.0, 28)],
                [("‘Signup event’ decreased by 50% yesterday", "500 yesterday · 1,000 on an average Monday", "risk")],
            ),
        )
