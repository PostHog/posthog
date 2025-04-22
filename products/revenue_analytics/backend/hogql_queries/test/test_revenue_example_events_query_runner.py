from decimal import Decimal
from unittest.mock import patch

from freezegun import freeze_time

from posthog.models.utils import uuid7
from posthog.schema import (
    CurrencyCode,
    RevenueCurrencyPropertyConfig,
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from products.revenue_analytics.backend.hogql_queries.revenue_example_events_query_runner import (
    RevenueExampleEventsQueryRunner,
)

EMPTY_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(events=[])

SINGLE_EVENT_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[RevenueTrackingEventItem(eventName="purchase", revenueProperty="revenue")]
)

MULTIPLE_EVENT_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[
        RevenueTrackingEventItem(eventName="purchase_a", revenueProperty="revenue_a"),
        RevenueTrackingEventItem(eventName="purchase_b", revenueProperty="revenue_b"),
    ]
)

REVENUE_TRACKING_CONFIG_WITH_REVENUE_CURRENCY_PROPERTY = RevenueTrackingConfig(
    events=[
        RevenueTrackingEventItem(
            eventName="purchase_a",
            revenueProperty="revenue_a",
            revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static=CurrencyCode.GBP),
        ),
        RevenueTrackingEventItem(
            eventName="purchase_b",
            revenueProperty="revenue_b",
            revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency_b"),
        ),
    ],
    baseCurrency=CurrencyCode.EUR,
)


@snapshot_clickhouse_queries
class TestRevenueExampleEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for distinct_id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person = _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[distinct_id],
                    properties={
                        "name": distinct_id,
                        **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
                    },
                )
            event_ids: list[str] = []
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                lcp_score = None
                revenue = None
                currency = None
                revenue_property = "revenue"
                currency_property = "currency"
                if event == "$pageview":
                    url = extra[0] if extra else None
                elif event == "$autocapture":
                    elements = extra[0] if extra else None
                elif event == "$web_vitals":
                    lcp_score = extra[0] if extra else None
                elif event.startswith("purchase"):
                    # purchase_a -> revenue_a/currency_a, purchase_b -> revenue_b/currency_b, etc
                    revenue_property += event[8:]
                    currency_property += event[8:]
                    revenue = extra[0] if extra else None
                    currency = extra[1] if extra and len(extra) > 1 else None

                event_ids.append(
                    _create_event(
                        team=self.team,
                        event=event,
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        properties={
                            "$session_id": session_id,
                            "$current_url": url,
                            "$web_vitals_LCP_value": lcp_score,
                            revenue_property: revenue,
                            currency_property: currency,
                        },
                        elements=elements,
                    )
                )
            person_result.append((person, event_ids))
        return person_result

    def _run_revenue_example_events_query(
        self,
        revenue_tracking_config: RevenueTrackingConfig,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            self.team.revenue_tracking_config = revenue_tracking_config.model_dump()
            self.team.save()

            runner = RevenueExampleEventsQueryRunner(team=self.team, query=RevenueExampleEventsQuery())

            response = runner.calculate()
            RevenueExampleEventsQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        results = self._run_revenue_example_events_query(EMPTY_REVENUE_TRACKING_CONFIG).results
        assert len(results) == 0

    def test_single_event(self):
        s11 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s11, 42)]),
            ],
            event="purchase",
        )

        results = self._run_revenue_example_events_query(SINGLE_EVENT_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 1
        assert results[0][1] == "purchase"
        assert results[0][2] == 42

    def test_multiple_events(self):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 42)]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 43)]),
            ],
            event="purchase_b",
        )

        results = self._run_revenue_example_events_query(MULTIPLE_EVENT_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 2
        assert results[0][1] == "purchase_b"
        assert results[0][2] == 43
        assert results[1][1] == "purchase_a"
        assert results[1][2] == 42

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_revenue_currency_property(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 42, "USD")]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 43, "BRL")]),
            ],
            event="purchase_b",
        )

        results = self._run_revenue_example_events_query(REVENUE_TRACKING_CONFIG_WITH_REVENUE_CURRENCY_PROPERTY).results

        assert len(results) == 2

        purchase_b, purchase_a = results

        # Stored USD on the event, but `purchase_a`'s revenueCurrencyProperty is set to static GBP
        assert purchase_a[1] == "purchase_a"
        assert purchase_a[2] == Decimal("42")
        assert purchase_a[3] == CurrencyCode.GBP.value
        assert purchase_a[4] == Decimal("48.841532819")  # 42 GBP -> 48.84 EUR
        assert purchase_a[5] == CurrencyCode.EUR.value

        assert purchase_b[1] == "purchase_b"
        assert purchase_b[2] == Decimal("43")
        assert purchase_b[3] == CurrencyCode.BRL.value
        assert purchase_b[4] == Decimal("8.0388947625")  # 43 BRL -> 8.03 EUR
        assert purchase_b[5] == CurrencyCode.EUR.value

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_revenue_currency_property_without_feature_flag(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 42, "USD")]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 43, "BRL")]),
            ],
            event="purchase_b",
        )

        results = self._run_revenue_example_events_query(REVENUE_TRACKING_CONFIG_WITH_REVENUE_CURRENCY_PROPERTY).results

        # Keep in the original revenue values
        assert len(results) == 2
        assert results[0][1] == "purchase_b"
        assert results[0][2] == 43
        assert results[1][1] == "purchase_a"
        assert results[1][2] == 42
