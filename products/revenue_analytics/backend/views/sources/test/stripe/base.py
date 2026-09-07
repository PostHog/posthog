"""
Base test class for revenue analytics Stripe source tests.

This module provides common setup and utilities specifically for testing
Stripe-based revenue analytics view sources.
"""

from typing import Optional
from uuid import uuid4

from posthog.schema import CurrencyCode

from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.sources.test.base import RevenueAnalyticsViewSourceBaseTest
from products.warehouse_sources.backend.facade.contracts import RevenueSource, RevenueSourceSchema, RevenueSourceTable
from products.warehouse_sources.backend.facade.sources import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)


def create_mock_stripe_external_data_source(team, schemas: Optional[list[str]] = None):
    """
    Create a mock external data source for Stripe with specified schemas.

    Args:
        team: The team to associate with the external data source
        schemas: List of schema names to include (defaults to all Stripe schemas)

    Returns:
        Mock ExternalDataSource with associated schemas and tables
    """
    if schemas is None:
        schemas = [
            CHARGE_RESOURCE_NAME,
            CUSTOMER_RESOURCE_NAME,
            INVOICE_RESOURCE_NAME,
            PRODUCT_RESOURCE_NAME,
            SUBSCRIPTION_RESOURCE_NAME,
        ]

    prefix = "stripe_test"
    source_schemas = []
    for schema_name in schemas:
        source_schemas.append(
            RevenueSourceSchema(
                name=schema_name,
                table=RevenueSourceTable(id=uuid4(), name=f"{prefix}_{schema_name.lower()}"),
            )
        )

    return RevenueSource(
        id=uuid4(),
        source_type="stripe",
        prefix=prefix,
        enabled=True,
        include_invoiceless_charges=True,
        schemas=tuple(source_schemas),
    )


def create_mock_stripe_table(team, table_name, schema_name=None):
    """
    Create a mock DataWarehouseTable for a specific Stripe resource.

    Args:
        team: The team to associate with the table
        table_name: Name of the table
        schema_name: Optional schema name (defaults to table_name)

    Returns:
        Mock DataWarehouseTable
    """
    if schema_name is None:
        schema_name = table_name

    return RevenueSourceTable(id=uuid4(), name=table_name)


def create_mock_stripe_schema(source, schema_name: str, table=None):
    """
    Create a mock ExternalDataSchema for a specific Stripe resource.

    Args:
        source: The external data source to associate with
        schema_name: Name of the schema (e.g., CHARGE_RESOURCE_NAME)
        table: Optional table to associate (creates one if not provided)

    Returns:
        Mock ExternalDataSchema
    """
    return RevenueSourceSchema(name=schema_name, table=table)


class StripeSourceBaseTest(RevenueAnalyticsViewSourceBaseTest):
    """
    Base test class for Stripe source revenue analytics tests.

    Provides common setup for testing Stripe-based revenue analytics views,
    including mock external data sources, schemas, and helper methods.
    """

    def setup_stripe_external_data_source(self, schemas: Optional[list[str]] = None):
        """
        Create a mock Stripe external data source with specified schemas.

        Args:
            schemas: List of schema names to include (defaults to all Stripe schemas)

        This creates:
        - self.external_data_source: Mock ExternalDataSource
        - self.stripe_handle: SourceHandle for the external data source
        """
        if schemas is None:
            schemas = [
                CHARGE_RESOURCE_NAME,
                CUSTOMER_RESOURCE_NAME,
                INVOICE_RESOURCE_NAME,
                PRODUCT_RESOURCE_NAME,
                SUBSCRIPTION_RESOURCE_NAME,
            ]

        self.external_data_source = create_mock_stripe_external_data_source(team=self.team, schemas=schemas)

        self.stripe_handle = SourceHandle(type="stripe", team=self.team, source=self.external_data_source)

    def setup_stripe_external_data_source_with_specific_schemas(self, schema_configs: list[dict]):
        """
        Create a mock Stripe external data source with specific schema configurations.

        Args:
            schema_configs: List of dictionaries with schema configuration:
                [{"name": "charge", "table_name": "stripe_charges"}, ...]
        """
        schemas: list[RevenueSourceSchema] = []

        for config in schema_configs:
            schema_name = config["name"]
            table_name = config.get("table_name", f"stripe_{schema_name.lower()}")

            table = (
                create_mock_stripe_table(team=self.team, table_name=table_name, schema_name=schema_name)
                if table_name is not None
                else None
            )

            schema = create_mock_stripe_schema(
                source=self.external_data_source if hasattr(self, "external_data_source") else None,
                schema_name=schema_name,
                table=table,
            )

            schemas.append(schema)

        # Create the external data source if it doesn't exist
        if not hasattr(self, "external_data_source"):
            self.external_data_source = create_mock_stripe_external_data_source(team=self.team, schemas=[])

        self.external_data_source = RevenueSource(
            id=self.external_data_source.id,
            source_type=self.external_data_source.source_type,
            prefix=self.external_data_source.prefix,
            enabled=self.external_data_source.enabled,
            include_invoiceless_charges=self.external_data_source.include_invoiceless_charges,
            schemas=tuple(schemas),
        )

        self.stripe_handle = SourceHandle(type="stripe", team=self.team, source=self.external_data_source)

    def get_stripe_schema_by_name(self, schema_name):
        """
        Get a specific schema by name from the external data source.

        Args:
            schema_name: The name of the schema to retrieve

        Returns:
            Mock ExternalDataSchema or None if not found
        """
        return next((schema for schema in self.external_data_source.schemas if schema.name == schema_name), None)

    def get_stripe_table_by_schema_name(self, schema_name):
        """
        Get a specific table by schema name from the external data source.

        Args:
            schema_name: The name of the schema to get the table for

        Returns:
            Mock DataWarehouseTable or None if not found
        """
        schema = self.get_stripe_schema_by_name(schema_name)
        return schema.table if schema else None

    def create_stripe_handle_without_source(self):
        """
        Create a SourceHandle without an external data source.

        Returns:
            SourceHandle with source=None for testing error cases
        """
        return SourceHandle(type="stripe", team=self.team, source=None)

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
