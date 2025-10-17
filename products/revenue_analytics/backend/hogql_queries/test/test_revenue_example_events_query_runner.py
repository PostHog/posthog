from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from posthog.schema import (
    CurrencyCode,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
)

from posthog.models.utils import uuid7

from products.revenue_analytics.backend.hogql_queries.revenue_example_events_query_runner import (
    RevenueExampleEventsQueryRunner,
)

REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE = RevenueAnalyticsEventItem(eventName="purchase", revenueProperty="revenue")
REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_A = RevenueAnalyticsEventItem(
    eventName="purchase_a", revenueProperty="revenue_a"
)
REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_B = RevenueAnalyticsEventItem(
    eventName="purchase_b", revenueProperty="revenue_b"
)
REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_C = RevenueAnalyticsEventItem(
    eventName="purchase_c", revenueProperty="revenue_c"
)

REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT_REVENUE_CURRENCY_PROPERTY = [
    REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_A.model_copy(
        update={"revenueCurrencyProperty": RevenueCurrencyPropertyConfig(static=CurrencyCode.GBP)}
    ),
    REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_B.model_copy(
        update={"revenueCurrencyProperty": RevenueCurrencyPropertyConfig(property="currency_b")}
    ),
    REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_C.model_copy(
        update={"revenueCurrencyProperty": RevenueCurrencyPropertyConfig(property="currency_c")}
    ),
]


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

    def _run_revenue_example_events_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            runner = RevenueExampleEventsQueryRunner(team=self.team, query=RevenueExampleEventsQuery())

            response = runner.calculate()
            RevenueExampleEventsQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        results = self._run_revenue_example_events_query().results
        assert len(results) == 0

    def test_single_event(self):
        s11 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s11, 42)]),
            ],
            event="purchase",
        )

        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE.model_dump()]
        self.team.revenue_analytics_config.save()

        results = self._run_revenue_example_events_query().results

        assert len(results) == 1
        assert results[0][1] == "purchase"
        assert results[0][2] == 42
        assert results[0][3] == 42  # No conversion because assumed to not be in smallest unit

    def test_single_event_with_smallest_unit_divider(self):
        s11 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s11, 4200)]),
            ],
            event="purchase",
        )

        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE.model_copy(update={"currencyAwareDecimal": True}).model_dump()
        ]
        self.team.revenue_analytics_config.save()

        results = self._run_revenue_example_events_query().results

        assert len(results) == 1
        assert results[0][1] == "purchase"
        assert results[0][2] == 4200
        assert results[0][3] == 42

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

        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_A.model_dump(),
            REVENUE_ANALYTICS_CONFIG_EVENT_PURCHASE_B.model_dump(),
        ]
        self.team.revenue_analytics_config.save()

        results = self._run_revenue_example_events_query().results

        assert len(results) == 2
        assert results[0][1] == "purchase_b"
        assert results[0][2] == 43
        assert results[0][3] == 43  # No conversion because assumed to not be in smallest unit
        assert results[1][1] == "purchase_a"
        assert results[1][2] == 42
        assert results[1][3] == 42  # No conversion because assumed to not be in smallest unit

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_revenue_currency_property(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 4200, "USD")]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 4300, "BRL")]),
            ],
            event="purchase_b",
        )
        s3 = str(uuid7("2023-12-04"))
        self._create_events(
            [
                ("p3", [("2023-12-04", s3, 1800, "JPY")]),
            ],
            event="purchase_c",
        )

        self.team.base_currency = CurrencyCode.EUR.value
        self.team.revenue_analytics_config.events = [
            event.model_copy(update={"currencyAwareDecimal": True}).model_dump()
            for event in REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT_REVENUE_CURRENCY_PROPERTY
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        results = self._run_revenue_example_events_query().results

        assert len(results) == 3

        purchase_c, purchase_b, purchase_a = results

        # Stored USD on the event, but `purchase_a`'s revenueCurrencyProperty is set to static GBP
        assert purchase_a[1] == "purchase_a"
        assert purchase_a[2] == Decimal("4200")
        assert purchase_a[3] == Decimal("42")
        assert purchase_a[4] == CurrencyCode.GBP.value
        assert purchase_a[5] == Decimal("48.841532819")  # 42 GBP -> 48.84 EUR
        assert purchase_a[6] == CurrencyCode.EUR.value

        assert purchase_b[1] == "purchase_b"
        assert purchase_b[2] == Decimal("4300")
        assert purchase_b[3] == Decimal("43")
        assert purchase_b[4] == CurrencyCode.BRL.value
        assert purchase_b[5] == Decimal("8.0388947625")  # 43 BRL -> 8.03 EUR
        assert purchase_b[6] == CurrencyCode.EUR.value

        assert purchase_c[1] == "purchase_c"
        assert purchase_c[2] == Decimal("1800")
        assert purchase_c[3] == Decimal("1800")  # JPY is not divided by 100 because lowest denomination is whole
        assert purchase_c[4] == CurrencyCode.JPY.value
        assert purchase_c[5] == Decimal("11.3165930643")  # 1800 JPY -> 11.31 EUR
        assert purchase_c[6] == CurrencyCode.EUR.value

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_revenue_currency_property_without_smallest_unit_divider(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 42.25, "USD")]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 43.24, "BRL")]),
            ],
            event="purchase_b",
        )
        s3 = str(uuid7("2023-12-04"))
        self._create_events(
            [
                ("p3", [("2023-12-04", s3, 1826, "JPY")]),
            ],
            event="purchase_c",
        )

        self.team.base_currency = CurrencyCode.EUR.value
        self.team.revenue_analytics_config.events = [
            event.model_dump() for event in REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT_REVENUE_CURRENCY_PROPERTY
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        results = self._run_revenue_example_events_query().results

        assert len(results) == 3

        purchase_c, purchase_b, purchase_a = results

        # Stored USD on the event, but `purchase_a`'s revenueCurrencyProperty is set to static GBP
        assert purchase_a[1] == "purchase_a"
        assert purchase_a[2] == Decimal("42.25")
        assert purchase_a[3] == Decimal("42.25")
        assert purchase_a[4] == CurrencyCode.GBP.value
        assert purchase_a[5] == Decimal("49.1322562285")  # 42.25 GBP -> 49.13 EUR
        assert purchase_a[6] == CurrencyCode.EUR.value

        assert purchase_b[1] == "purchase_b"
        assert purchase_b[2] == Decimal("43.24")
        assert purchase_b[3] == Decimal("43.24")
        assert purchase_b[4] == CurrencyCode.BRL.value
        assert purchase_b[5] == Decimal("8.0837630123")  # 43.24 BRL -> 8.08 EUR
        assert purchase_b[6] == CurrencyCode.EUR.value

        assert purchase_c[1] == "purchase_c"
        assert purchase_c[2] == Decimal("1826")
        assert purchase_c[3] == Decimal("1826")  # JPY is not divided by 100 because lowest denomination is whole
        assert purchase_c[4] == CurrencyCode.JPY.value
        assert purchase_c[5] == Decimal("11.4800549642")  # 1826 JPY -> 11.48 EUR
        assert purchase_c[6] == CurrencyCode.EUR.value

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_revenue_currency_property_without_feature_flag(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 4200, "USD")]),
            ],
            event="purchase_a",
        )
        s2 = str(uuid7("2023-12-03"))
        self._create_events(
            [
                ("p2", [("2023-12-03", s2, 4300, "BRL")]),
            ],
            event="purchase_b",
        )
        s3 = str(uuid7("2023-12-04"))
        self._create_events(
            [
                ("p3", [("2023-12-04", s3, 1800, "JPY")]),
            ],
            event="purchase_c",
        )

        self.team.base_currency = CurrencyCode.EUR.value
        self.team.revenue_analytics_config.events = [
            event.model_copy(update={"currencyAwareDecimal": True}).model_dump()
            for event in REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT_REVENUE_CURRENCY_PROPERTY
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        results = self._run_revenue_example_events_query().results

        # Keep in the original revenue values
        assert len(results) == 3

        purchase_c, purchase_b, purchase_a = results

        assert purchase_c[1] == "purchase_c"
        assert purchase_c[3] == 1800  # JPY is not divided by 100 because lowest denomination is whole
        assert purchase_b[1] == "purchase_b"
        assert purchase_b[3] == 43
        assert purchase_a[1] == "purchase_a"
        assert purchase_a[3] == 42
