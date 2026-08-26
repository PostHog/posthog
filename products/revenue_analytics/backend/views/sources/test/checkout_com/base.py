"""
Base test class for revenue analytics Checkout.com source tests.

This module provides common setup and utilities specifically for testing
Checkout.com-based revenue analytics view sources.
"""

from typing import Optional
from uuid import uuid4

from posthog.schema import CurrencyCode

from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    CUSTOMER_RESOURCE_NAME,
    PAYMENT_ACTION_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.sources.test.base import RevenueAnalyticsViewSourceBaseTest
from products.warehouse_sources.backend.facade.contracts import RevenueSource, RevenueSourceSchema, RevenueSourceTable

ALL_CHECKOUT_COM_RESOURCE_NAMES = [
    PAYMENT_RESOURCE_NAME,
    PAYMENT_ACTION_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
]


def create_mock_checkout_com_external_data_source(team, schemas: Optional[list[str]] = None):
    """
    Create a mock external data source for Checkout.com with specified schemas.

    Args:
        team: The team to associate with the external data source
        schemas: List of schema names to include (defaults to all revenue-relevant schemas)

    Returns:
        RevenueSource with associated schemas and tables
    """
    if schemas is None:
        schemas = ALL_CHECKOUT_COM_RESOURCE_NAMES

    prefix = "checkout_test"
    source_schemas = [
        RevenueSourceSchema(
            name=schema_name,
            table=RevenueSourceTable(id=uuid4(), name=f"{prefix}_{schema_name.lower()}"),
        )
        for schema_name in schemas
    ]

    return RevenueSource(
        id=uuid4(),
        source_type="CheckoutCom",
        prefix=prefix,
        enabled=True,
        include_invoiceless_charges=True,
        schemas=tuple(source_schemas),
    )


class CheckoutComSourceBaseTest(RevenueAnalyticsViewSourceBaseTest):
    """
    Base test class for Checkout.com source revenue analytics tests.

    Provides common setup for testing Checkout.com-based revenue analytics views,
    including mock external data sources, schemas, and helper methods.
    """

    def setup_checkout_com_external_data_source(self, schemas: Optional[list[str]] = None):
        """
        Create a mock Checkout.com external data source with specified schemas.

        Args:
            schemas: List of schema names to include (defaults to all revenue-relevant schemas)

        This creates:
        - self.external_data_source: RevenueSource
        - self.checkout_com_handle: SourceHandle for the external data source
        """
        self.external_data_source = create_mock_checkout_com_external_data_source(team=self.team, schemas=schemas)
        self.checkout_com_handle = SourceHandle(type="checkoutcom", team=self.team, source=self.external_data_source)

    def get_checkout_com_schema_by_name(self, schema_name):
        """
        Get a specific schema by name from the external data source.

        Args:
            schema_name: The name of the schema to retrieve

        Returns:
            RevenueSourceSchema or None if not found
        """
        schemas = self.external_data_source.schemas
        return next((schema for schema in schemas if schema.name == schema_name), None)

    def get_checkout_com_table_by_schema_name(self, schema_name):
        """
        Get a specific table by schema name from the external data source.

        Args:
            schema_name: The name of the schema to get the table for

        Returns:
            RevenueSourceTable or None if not found
        """
        schema = self.get_checkout_com_schema_by_name(schema_name)
        return schema.table if schema else None

    def create_checkout_com_handle_without_source(self):
        """
        Create a SourceHandle without an external data source.

        Returns:
            SourceHandle with source=None for testing error cases
        """
        return SourceHandle(type="checkoutcom", team=self.team, source=None)

    def set_team_base_currency(self, currency_code: str):
        """
        Set the team's base currency.

        Args:
            currency_code: 3-letter currency code (e.g., "USD", "EUR")
        """
        if currency_code not in [code.value for code in CurrencyCode]:
            raise ValueError(f"Invalid currency code: {currency_code}")

        self.team.base_currency = currency_code
        self.team.save()
