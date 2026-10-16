import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.testing import create_access_control
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.insight_series import _table_series
from products.product_analytics.backend.models.insight import Insight


class TestTableSeries(SimpleTestCase):
    @parameterized.expand(
        [
            ("decimal values", [[date(2026, 10, d), Decimal("1.5")] for d in (1, 2, 3)], "day", 4.5),
            (
                "non-finite values are skipped",
                [[date(2026, 10, d), v] for d, v in ((1, 2.0), (2, math.inf))],
                "day",
                2.0,
            ),
            ("sparse daily data stays daily", [[date(2026, 10, d), 1] for d in (1, 2, 5, 9, 14)], "day", 5.0),
            ("weekly rows read as weeks", [[date(2026, 9, d), 2] for d in (7, 14, 21, 28)], "week", 8.0),
        ]
    )
    def test_a_table_with_a_date_column_becomes_a_series(
        self, _name: str, rows: list[list[Any]], period: str, total: float
    ) -> None:
        series, found = _table_series(["day", "value"], rows)

        self.assertEqual((found, sum(v for _, v in series["value"])), (period, total))


class TestGetInsightSeries(ClickhouseTestMixin, BaseTest):
    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    def _insight(self, **query: Any) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name="Sign-ups",
            created_by=self.user,
            saved=True,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", **query}},
        )

    def test_a_daily_trend_returns_its_series_and_display_format(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        for days in (2, 2, 9):
            _create_event(team=self.team, event="signed up", distinct_id="user-1", timestamp=self._ago(days))
        flush_persons_and_events()
        insight = self._insight(
            series=[{"kind": "EventsNode", "event": "signed up", "math": "dau"}],
            trendsFilter={"aggregationAxisFormat": "percentage"},
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        assert found is not None
        points = found.series["signed up"]
        self.assertEqual(
            (
                found.period,
                found.averaged,
                found.event_name,
                found.value_format,
                len(points),
                sum(v for _, v in points),
            ),
            ("day", True, "signed up", "percentage", 57, 2.0),
        )

    @parameterized.expand([("a table", {"trendsFilter": {"display": "ActionsTable"}}), ("a funnel", None)])
    def test_an_insight_without_a_time_series_returns_none(self, _name: str, query: dict[str, Any] | None) -> None:
        insight = (
            self._insight(series=[{"kind": "EventsNode", "event": "signed up"}], **query)
            if query
            else Insight.objects.create(
                team=self.team, query={"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}}
            )
        )

        self.assertIsNone(get_insight_series(team=self.team, user=self.user, short_id=insight.short_id))

    def test_an_insight_the_person_cannot_view_returns_none(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        insight = self._insight(series=[{"kind": "EventsNode", "event": "signed up"}])
        create_access_control(
            team_id=self.team.id, resource="insight", resource_id=str(insight.id), access_level="none"
        )
        reader = self._create_user("reader@example.com")

        self.assertIsNone(get_insight_series(team=self.team, user=reader, short_id=insight.short_id))
