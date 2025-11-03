# Revenue Analytics Views

This module provides a flexible architecture for generating revenue analytics views from multiple data sources (events and external data warehouse sources like Stripe). It transforms raw data into standardized schemas for revenue analysis across different view types.

## Architecture Overview

The system follows a builder pattern where:

1. **Sources** define how to extract data from different systems (events, Stripe, etc.)
2. **Schemas** define the standardized output format for each view type
3. **Orchestrator** coordinates the process and builds concrete view instances
4. **Views** are the final HogQL queries registered in the database schema

```text
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌───────────────┐
│   Sources   │───▶│   Builders   │───▶│   Orchestrator  │───▶│  View Objects │
│             │    │              │    │                 │    │               │
│ • Events    │    │ • Transform  │    │ • Coordinates   │    │ • HogQL Query │
│ • Stripe    │    │ • Normalize  │    │ • Applies       │    │ • Schema      │
│ • Other DW  │    │ • Convert    │    │   schemas       │    │ • Metadata    │
└─────────────┘    └──────────────┘    └─────────────────┘    └───────────────┘
```

## Core Components

### 1. View Types (5 standardized views)

- **Charge**: Individual payment transactions
- **Customer**: Customer profiles and metadata
- **Product**: Product/service definitions
- **Revenue Item**: Line items from invoices/subscriptions
- **Subscription**: Recurring subscription data

### 2. Data Sources

1. Events (`sources/events/`): Transforms PostHog events into revenue views using team-configured revenue events.
2. Stripe (`sources/stripe/`)

### 3. Schema System

Each view type has a predefined schema (`schemas/`) that ensures consistency across sources:

```python
# Example: Charge schema
FIELDS = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "amount": DecimalDatabaseField(name="amount"),
    "currency": StringDatabaseField(name="currency"),
    # ... plus currency conversion fields
}
```

## Adding New Data Warehouse Sources

To extend the system with a new data warehouse source (e.g., Chargebee, RevenueCat, Polar, etc.), follow these steps:

### Step 1: Add Source Type Support

Add your source type to `orchestrator.py`:

```python
SUPPORTED_SOURCES: list[ExternalDataSourceType] = [
    ExternalDataSourceType.STRIPE,
    ExternalDataSourceType.CHARGEBEE,  # Add your source
]
```

### Step 2: Create Source Builders

Create a new directory `sources/chargebee/` with builder modules for each view type:

```text
sources/chargebee/
├── __init__.py
├── charge.py
├── customer.py
├── product.py
├── revenue_item.py
└── subscription.py
```

### Step 3: Implement Builders

Each builder must implement the `Builder` function signature:

```python
# sources/chargebee/charge.py
from typing import Iterable
from posthog.hogql import ast
from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source

def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    source = handle.source
    if source is None:
        return

    # Find the relevant schema/table for this source
    schemas = source.schemas.all()
    charge_schema = next((s for s in schemas if s.name == "Charge"), None)
    if charge_schema is None or charge_schema.table is None:
        return

    table = charge_schema.table
    prefix = view_prefix_for_source(source)

    # Build HogQL AST that transforms source data to match charge schema
    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            # Map source fields to schema fields
            # Handle currency conversion using helpers from sources.helpers
            # ...
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
        where=ast.CompareOperation(
            left=ast.Field(chain=["status"]),
            right=ast.Constant(value="paid"),
            op=ast.CompareOperationOp.Eq,
        ),
    )

    yield BuiltQuery(key=str(table.id), prefix=prefix, query=query)
```

### Step 4: Register Builders

Create the builder registry in `sources/chargebee/__init__.py`:

```python
from posthog.schema import DatabaseSchemaManagedViewTableKind
from products.revenue_analytics.backend.views.core import Builder

from .charge import build as charge_builder
from .customer import build as customer_builder
from .product import build as product_builder
from .revenue_item import build as revenue_item_builder
from .subscription import build as subscription_builder

BUILDER: Builder = {
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE: charge_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER: customer_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT: product_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM: revenue_item_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION: subscription_builder,
}
```

### Step 5: Register in Global Registry

Add your builder to `sources/registry.py`:

```python
from products.revenue_analytics.backend.views.sources.chargebee import BUILDER as CHARGEBEE_BUILDER

BUILDERS: Dict[str, Builder] = {
    "events": EVENTS_BUILDER,
    "stripe": STRIPE_BUILDER,
    "chargebee": CHARGEBEE_BUILDER,  # Add this line
}
```

## Implementation Guidelines

### Currency Handling

Use the currency helpers from `sources/helpers.py` for proper currency conversion:

```python
from products.revenue_analytics.backend.views.sources.helpers import (
    currency_aware_divider,
    currency_aware_amount,
)

# In your builder's select:
ast.Alias(alias="original_currency", expr=ast.Field(chain=["currency"])),
ast.Alias(alias="original_amount", expr=ast.Field(chain=["amount"])),
currency_aware_divider(),  # Handles zero-decimal currencies
currency_aware_amount(),   # Converts to proper decimal amount
```

### Field Mapping

Each builder must map source fields to the standardized schema fields. Reference existing schemas in `schemas/` to understand required fields.

### Error Handling

- Return empty iterator if required schemas/tables don't exist
- Use graceful degradation - missing optional fields should not break the build
- Consider prefetching related data to avoid N+1 queries

### Naming Conventions

- **Source builders**: Match the lowercase source type (e.g., "stripe", "chargebee")
- **Table names**: Match exact schema names from the external source
- **View names**: Auto-generated using `view_name_for_source()` helper

## Helper Functions

### Currency Conversion

- `currency_aware_divider()`: Handles zero-decimal currencies (JPY, KRW, etc.)
- `currency_aware_amount()`: Applies proper decimal conversion
- `is_zero_decimal_in_stripe()`: Checks if currency needs division

### Naming

- `view_prefix_for_source()`: Generates view prefix from source config
- `view_name_for_source()`: Full view name with suffix

### Data Extraction

- `extract_json_string()`: Extract nested JSON fields
- `extract_json_uint()`: Extract nested JSON numbers
- `get_cohort_expr()`: Generate cohort grouping expressions

## Testing Your Implementation

### Testing Architecture Overview

The testing system follows a structured approach with dedicated test suites for each source type. Each source has its own test directory with comprehensive coverage of builders, edge cases, and integration scenarios.

#### Test Directory Structure

```text
sources/test/
├── base.py                          # Core testing infrastructure
├── events/                          # Event source tests
│   ├── base.py                     # Events-specific base test class
│   ├── test_charge.py              # Charge builder tests
│   ├── test_customer.py            # Customer builder tests
│   ├── test_product.py             # Product builder tests
│   ├── test_revenue_item.py        # Revenue item builder tests
│   ├── test_subscription.py        # Subscription builder tests
│   └── __snapshots__/              # Query snapshots for regression testing
└── stripe/                         # Stripe source tests
    ├── base.py                     # Stripe-specific base test class
    ├── test_stripe_charge.py       # Stripe charge builder tests
    ├── test_stripe_customer.py     # Stripe customer builder tests
    ├── test_stripe_product.py      # Stripe product builder tests
    ├── test_stripe_revenue_item.py # Stripe revenue item builder tests
    ├── test_stripe_subscription.py # Stripe subscription builder tests
    └── __snapshots__/              # Query snapshots for regression testing
```

#### Base Test Classes

**1. Core Base Test (`sources/test/base.py`)**

- `RevenueAnalyticsViewSourceBaseTest`: Provides fundamental testing infrastructure
- Includes ClickHouse query testing capabilities
- Query snapshot testing with `assertQueryMatchesSnapshot`
- API testing infrastructure
- Common assertion helpers for query structure validation

**2. Source-Specific Base Tests**

- `EventsSourceBaseTest`: Specialized for event-based revenue analytics
    - Revenue analytics event configuration helpers
    - Team base currency management
    - Event clearing and setup utilities
- `StripeSourceBaseTest`: Specialized for Stripe external data sources
    - Mock external data source and schema creation
    - Stripe-specific test fixtures and helpers
    - Currency validation and testing support

#### Testing Guidelines for New Sources

When adding a new source (e.g., Chargebee), follow this testing pattern:

**1. Create Source Test Directory**

```bash
mkdir sources/test/chargebee/
```

**2. Create Base Test Class (`sources/test/chargebee/base.py`)**

```python
"""
Base test class for revenue analytics Chargebee source tests.
"""
from unittest.mock import Mock
from uuid import uuid4
from typing import List, Dict, Optional

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource, DataWarehouseTable
from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.sources.test.base import RevenueAnalyticsViewSourceBaseTest

# Mock creation functions
def create_mock_chargebee_external_data_source(team, schemas: Optional[List[str]] = None):
    """Create mock external data source for Chargebee with specified schemas."""
    # Implementation similar to Stripe pattern
    pass

class ChargebeeSourceBaseTest(RevenueAnalyticsViewSourceBaseTest):
    """Base test class for Chargebee source revenue analytics tests."""

    def setup_chargebee_external_data_source(self, schemas: Optional[List[str]] = None):
        """Create a mock Chargebee external data source with specified schemas."""
        pass

    def get_chargebee_schema_by_name(self, schema_name: str):
        """Get a specific schema by name from the external data source."""
        pass
```

**3. Create Individual Builder Tests**

Each builder should have comprehensive test coverage:

```python
# sources/test/chargebee/test_chargebee_charge.py
from products.revenue_analytics.backend.views.sources.chargebee.charge import build
from products.revenue_analytics.backend.views.sources.test.chargebee.base import ChargebeeSourceBaseTest
from products.revenue_analytics.backend.views.schemas.charge import SCHEMA as CHARGE_SCHEMA

class TestChargeChargebeeBuilder(ChargebeeSourceBaseTest):
    def test_build_charge_query_with_charge_schema(self):
        """Test building charge query when charge schema exists."""
        # Happy path testing
        pass

    def test_build_with_no_charge_schema(self):
        """Test that build returns empty when no charge schema exists."""
        # Error case testing
        pass

    def test_build_with_no_source(self):
        """Test that build returns empty when source is None."""
        # Edge case testing
        pass

    def test_charge_query_contains_required_fields(self):
        """Test that the generated query contains all required charge fields."""
        # Field validation testing
        pass
```

#### Snapshot Testing

Use snapshot testing for regression protection on generated HogQL queries:

```python
def test_build_charge_query_snapshot(self):
    """Test that generated query matches expected structure."""
    self.setup_chargebee_external_data_source(schemas=[CHARGE_RESOURCE_NAME])

    queries = list(build(self.chargebee_handle))
    charge_query = queries[0]

    query_sql = charge_query.query.to_hogql()
    self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)
```

#### Assertion Helpers

Use the provided assertion helpers for consistent testing:

```python
# Test query structure
self.assertBuiltQueryStructure(
    built_query,
    expected_key,
    expected_prefix
)

# Test schema compliance
self.assertQueryContainsFields(query, schema)

# Test currency handling
self.set_team_base_currency("EUR")
# ... test currency conversion logic
```

### Running Tests

**1. Orchestrator Tests**

```bash
pytest products/revenue_analytics/backend/views/test/test_orchestrator.py -v
```

**2. Source-Specific Tests**

```bash
# Test all events source builders
pytest products/revenue_analytics/backend/views/sources/test/events/ -v --snapshot-update

# Test all Stripe source builders
pytest products/revenue_analytics/backend/views/sources/test/stripe/ -v --snapshot-update

# Test specific builder
pytest products/revenue_analytics/backend/views/sources/test/stripe/test_stripe_charge.py -v --snapshot-update
```

**3. HogQL Query Integration Tests**

These are useful to know whether changes in your code produced any change on the output queries

```bash
pytest products/revenue_analytics/backend/hogql_queries/test/ -v --snapshot-update
```

### Testing your implementation via queries

There are many more tests in `products/revenue_analytics/backend/hogql_queries/test/` which are currently only testing Stripe and events. It's usually a wise idea to extend that with your new source.

## View Registration

Views are automatically registered in PostHog's HogQL database schema through the orchestrator. The system will:

1. Discover your source through `ExternalDataSource` records
2. Run your builders for each supported view type
3. Apply the standardized schema to your generated queries
4. Register views with names like `{source_type}.{prefix}.{view_suffix}`

Example view names:

- `chargebee.production.charge_revenue_view`
- `chargebee.customer_revenue_view`

The `prefix` comes from the `ExternalDataSource.prefix` field, allowing multiple instances of the same source type - and, of course, it can be empty.
