"""
Base test class for revenue analytics events source tests.

This module provides common setup and utilities specifically for testing
event-based revenue analytics view sources.
"""

from posthog.schema import CurrencyCode, RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from products.revenue_analytics.backend.views.sources.test.base import RevenueAnalyticsViewSourceBaseTest


class EventsSourceBaseTest(RevenueAnalyticsViewSourceBaseTest):
    """
    Base test class for events source revenue analytics tests.

    Provides common setup for testing event-based revenue analytics views,
    including sample event configurations and helper methods.
    """

    PURCHASE_EVENT_NAME = "purchase"
    SUBSCRIPTION_CHARGE_EVENT_NAME = "subscription_charge"

    def setup_revenue_analytics_events(self):
        """
        Configure default revenue analytics events for testing.

        Sets up common event configurations that can be used across tests.
        Individual tests can override these by calling configure_events() with
        their own configurations.

        This needs to be explicitly called in the test class setUp method.
        """
        self.configure_events(
            [
                {
                    "eventName": self.PURCHASE_EVENT_NAME,
                    "revenueProperty": "amount",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                },
                {
                    "eventName": self.SUBSCRIPTION_CHARGE_EVENT_NAME,
                    "revenueProperty": "price",
                    "currencyAwareDecimal": False,
                    "revenueCurrencyProperty": {"property": "currency"},
                    "productProperty": "product_id",
                    "subscriptionProperty": "subscription_id",
                },
            ]
        )

    def configure_events(self, events_config):
        """
        Configure revenue analytics events for the test team.

        Args:
            events_config: List of event configuration dictionaries
        """
        # Validate and set events using the schema
        validated_events = []
        for event_config in events_config:
            # Create a copy to avoid modifying the original
            config_copy = dict(event_config)

            # Ensure revenueCurrencyProperty has proper structure
            if "revenueCurrencyProperty" in config_copy:
                currency_config = config_copy["revenueCurrencyProperty"]
                config_copy["revenueCurrencyProperty"] = RevenueCurrencyPropertyConfig.model_validate(currency_config)

            validated_events.append(RevenueAnalyticsEventItem.model_validate(config_copy).model_dump())

        self.team.revenue_analytics_config.events = validated_events
        self.team.revenue_analytics_config.save()

    def clear_events(self):
        """Clear all revenue analytics events for the test team."""
        self.team.revenue_analytics_config.events = []
        self.team.revenue_analytics_config.save()

    def set_team_base_currency(self, currency_code: str):
        """
        Set the team's base currency.

        Args:
            currency_code: 3-letter currency code (e.g., "USD", "EUR")
        """
        if currency_code not in CurrencyCode._value2member_map_:
            raise ValueError(f"Invalid currency code: {currency_code}")

        self.team.base_currency = currency_code
        self.team.save()
