import uuid
from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.alerts.backend.facade.contracts import FiringAlert
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import alerts
from products.today.backend.logic.highlight_types import Context


class TestAlerts(BaseTest):
    @parameterized.expand(
        [
            (
                "the kind word is cut from the alert name",
                "Checkout conversion alert",
                "Checkout funnel",
                "Alert ‘Checkout conversion’ is firing",
                "Insight ‘Checkout funnel’",
            ),
            ("an unnamed insight shows its id", "Signups", None, "Alert ‘Signups’ is firing", "Insight ‘abc123’"),
            ("an unnamed alert", "", "Checkout funnel", "An alert is firing", "Insight ‘Checkout funnel’"),
        ]
    )
    def test_each_firing_alert_is_one_risk_item(
        self, _name: str, alert_name: str, insight_name: str | None, title: str, detail: str
    ) -> None:
        alert = FiringAlert(id=uuid.uuid4(), name=alert_name, insight_name=insight_name, insight_short_id="abc123")
        registered = next(s for s in load_sources() if s.name == "alerts")

        with patch.object(alerts, "list_firing_alerts_created_by", return_value=[alert]):
            found = registered.find(Context(self.team, self.user, date(2026, 10, 13)))

        self.assertEqual(
            [(c.key, c.title, c.detail, c.url) for c in found.items],
            [(f"alert:{alert.id}", title, detail, "/insights/abc123")],
        )

    @parameterized.expand(
        [
            ("a session", None, True),
            ("a key with the metrics scope", frozenset({"alert:read", "metrics:read"}), True),
            ("a key without it", frozenset({"alert:read"}), False),
        ]
    )
    def test_metrics_insight_alerts_follow_the_metrics_scope(
        self, _name: str, scopes: frozenset[str] | None, include: bool
    ) -> None:
        listed = MagicMock(return_value=[])
        registered = next(s for s in load_sources() if s.name == "alerts")

        with patch.object(alerts, "list_firing_alerts_created_by", listed):
            registered.find(Context(self.team, self.user, date(2026, 10, 13), scopes))

        self.assertEqual(listed.call_args.kwargs["include_metrics_insights"], include)
