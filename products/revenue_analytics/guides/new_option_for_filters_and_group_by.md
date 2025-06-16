# How to add a new option for Revenue Analytics filters and group by

This guide explains all the steps required to add a new option that can be used both as a filter and as a group by (breakdown) option in Revenue Analytics. This is based on the implementation of the "country" option.

## Overview

Adding a new filter/breakdown option in Revenue Analytics requires changes across multiple layers:

1. **Frontend schema definitions** - Define the new property type
1. **Taxonomy system** - Define filter metadata for the UI
1. **Database view updates** - Ensure required fields are available
1. **HogQL property handling** - Map the property to database fields
1. **Base query runner updates** - Handles making sure the revenue query runners handle new properties
1. **Insights query runner update** - Handles making sure we know how to breakdown by new property
    1. This will be updated soon to be much more simple and generic, similar to the point above
1. **API endpoints** - Add value fetching for filter dropdowns
1. **Frontend components** - Add UI controls and feature flags

## Step-by-Step Implementation

### 1. Frontend Schema Definition

**File**: `frontend/src/queries/schema/schema-general.ts`

```typescript
export type RevenueAnalyticsInsightsQueryGroupBy = 'all' | 'product' | 'cohort' | 'country'
```

**Purpose**: TypeScript equivalent of the backend schema for frontend type safety.

**Important**: After updating this file, run `pnpm build:schema` to generate the JSON and Python files that synchronize schemas between frontend and backend.

### 2. Taxonomy Definition

**File**: `posthog/taxonomy/taxonomy.py`

Add to the `CORE_FILTER_DEFINITIONS_BY_GROUP` under the `"revenue_analytics"` group:

```python
"country": {
    "label": "Country",
    "description": "The country of the customer connected to the revenue event.",
    "type": "String",
},
```

**Purpose**: Defines metadata for the filter that's used in the UI for labels, descriptions, and filter types.

**Important**: After updating this file, run `pnpm build:taxonomy` to generate the JSON file used by the frontend.

### 3. Database View Updates

**File**: `products/revenue_analytics/backend/views/revenue_analytics_customer_view.py`

Ensure required fields are available in the view:

```python
# Add to FIELDS dictionary
FIELDS: dict[str, FieldOrTable] = {
    "customer_id": StringDatabaseField(name="customer_id"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
    "cohort": StringDatabaseField(name="cohort"),

    # These two were added
    "address": StringJSONDatabaseField(name="address"),
    "country": StringDatabaseField(name="country"),
}

# Add to select fields in query generation
def get_query_for_source(cls, source: ExternalDataSource) -> ast.SelectQuery:
    # ... existing code ...
    select=[
        ast.Alias(alias="customer_id", expr=ast.Field(chain=["id"])),
        ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
        ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
        ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
        ast.Alias(alias="cohort", expr=ast.Constant(value=None)),

        # These two were added
        ast.Alias(alias="address", expr=ast.Field(chain=["address"])),
        ast.Alias(alias="country", expr=ast.Call(name="JSONExtractString", args=[ast.Field(chain=["address"]), ast.Constant(value="country")])),
    ],
```

**Purpose**: Ensures the database view includes all fields needed for the new property.

### 4. HogQL Property Mapping

**File**: `posthog/hogql/property.py`

Add property mapping in `create_expr_for_revenue_analytics_property()`:

```python
def create_expr_for_revenue_analytics_property(property: RevenueAnalyticsPropertyFilter) -> ast.Expr:
    if property.key == "amount":
        return ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"])
    elif property.key == "product":
        return ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "name"])
    elif property.key == "country":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "country"])
    # ... other properties
```

**Purpose**: Maps the property key to the actual database field path for use in HogQL queries.

### 5. Query Runner Property Dependencies

**File**: `products/revenue_analytics/backend/hogql_queries/revenue_analytics_query_runner.py`

Update `joins_set_for_properties` to include necessary joins:

```python
@cached_property
def joins_set_for_properties(self) -> set[str]:
    joins_set = set()
    for property in self.query.properties:
        if property.key == "product":
            joins_set.add("products")
        elif property.key == "country":
            joins_set.add("customers")  # Add join requirement
        elif property.key == "customer":
            joins_set.add("customers")
    return joins_set
```

**Purpose**: Ensures that when the property is used in filters, the necessary table joins are automatically included.

### 6. GroupBy Implementation

**File**: `products/revenue_analytics/backend/hogql_queries/revenue_analytics_insights_query_runner.py`

Add the new groupBy case in `_get_subquery()`:

```python
def _get_subquery(self) -> ast.SelectQuery | None:
    if self.query.groupBy == "all":
        return self._get_subquery_by_all()
    elif self.query.groupBy == "product":
        return self._get_subquery_by_product()
    elif self.query.groupBy == "country":
        return self._get_subquery_by_country()  # Add this line
    elif self.query.groupBy == "cohort":
        return self._get_subquery_by_cohort()
```

Then implement the actual method (note: this was missing in the diff):

```python
def _get_subquery_by_country(self) -> ast.SelectQuery | None:
    _, customer_subquery, invoice_item_subquery, _ = self.revenue_subqueries
    if invoice_item_subquery is None:
        return None

    query = ast.SelectQuery(
        select=[
            ast.Alias(
                alias="breakdown_by",
                expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
            ),
            ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
            ast.Alias(
                alias="day_start",
                expr=ast.Call(
                    name=f"toStartOf{self.query_date_range.interval_name.title()}",
                    args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                ),
            ),
        ],
        select_from=self.append_joins(
            ast.JoinExpr(
                alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                table=invoice_item_subquery,
            ),
            self.joins_for_properties,
        ),
        where=ast.And(
            exprs=[
                self.timestamp_where_clause(
                    chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                ),
                *self.where_property_exprs,
            ]
        ),
    )

    # Join with customer to get access to the `country`
    # and also change the `breakdown_by` to include that
    if customer_subquery is not None:
        # This `if` is required to make mypy happy
        if (
            query.select
            and query.select[0]
            and isinstance(query.select[0], ast.Alias)
            and query.select[0].alias == "breakdown_by"
        ):
            query.select[0].expr = ast.Call(
                name="concat",
                args=[
                    ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                    ast.Constant(value=" - "),
                    ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "country"]),
                            ast.Constant(value=NO_BREAKDOWN_PLACEHOLDER),
                        ],
                    ),
                ],
            )

        # We wanna include a join with the customer table to get the country
        # and also change the `breakdown_by` to include that
        # However, because we're already likely joining with the customer because
        # we might be filtering on item, we need to be extra safe here and guarantee
        # there's no join with the customer table before adding this one
        if query.select_from is not None:
            has_customer_join = False
            current_join: ast.JoinExpr | None = query.select_from
            while current_join is not None:
                if current_join.alias == RevenueAnalyticsCustomerView.get_generic_view_alias():
                    has_customer_join = True
                    break
                current_join = current_join.next_join

            if not has_customer_join:
                query.select_from = self.append_joins(
                    query.select_from,
                    [self.create_customer_join(customer_subquery)],
                )

    return query
```

**Purpose**: Implements the actual groupBy logic for breakdowns, combining revenue data with the new dimension.

### 7. API Values Endpoint

**File**: `products/revenue_analytics/backend/api.py`

Add value fetching logic in the `values` action so that you return all possible values for that specific new field:

```python
@action(methods=["GET"], detail=False)
def values(self, request: Request, **kwargs):
    key = request.GET.get("key")
    database = create_hogql_database(team=self.team)

    query = None
    values = []
    # ... existing cases ...
    elif key == "country":  # All countries available from revenue analytics
        query = ast.SelectQuery(
            select=[ast.Alias(alias="country", expr=ast.Field(chain=["country"]))],
            distinct=True,
            select_from=ast.JoinExpr(table=self._customer_selects(revenue_selects)),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["country"]), order="ASC")],
        )
```

You might need to create a new equivalent to `self._customer_selects` that should use `revenue_selects` and filter from it.

**Purpose**: Provides the dropdown values for the filter UI by querying all unique values available in the database.

### 8. Frontend Component Integration

**File**: `products/revenue_analytics/frontend/tiles/GrossRevenueTile.tsx`

Add the new option to the UI, possibly hiding it behind a feature flag:

```tsx
const GROUP_BY_OPTIONS: LemonSegmentedButtonOption<RevenueAnalyticsInsightsQueryGroupBy>[] = [
    { label: 'All', value: 'all' },
    { label: 'Product', value: 'product' },
    { label: 'Cohort', value: 'cohort' },
    {
        label: 'Country',
        value: 'country',
        disabledReason: featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS_COUNTRY_GROUPING] ? undefined : 'Coming soon',
    },
]
```

### 9. Feature Flag Definition

**File**: `frontend/src/lib/constants.tsx`

Add feature flag for the new option:

```tsx
export const FEATURE_FLAGS = {
    // ... existing flags ...
    REVENUE_ANALYTICS_COUNTRY_GROUPING: 'revenue-analytics-country-grouping',
}
```

**Purpose**: Allows gradual rollout and testing of the new feature.

## Build Commands

After making the necessary changes, run these commands to regenerate the auto-generated files:

```bash
# After updating posthog/taxonomy/taxonomy.py
pnpm build:taxonomy

# After updating frontend/src/queries/schema/schema-general.ts
pnpm build:schema
```

## Summary of Files to Modify

When adding a new Revenue Analytics filter/breakdown option, you need to modify these files:

1. **`frontend/src/queries/schema/schema-general.ts`** - Frontend schema type
1. **`posthog/taxonomy/taxonomy.py`** - Filter metadata definition
1. **`posthog/hogql/property.py`** - HogQL property mapping
1. **`products/revenue_analytics/backend/hogql_queries/revenue_analytics_query_runner.py`** - Join requirements
1. **`products/revenue_analytics/backend/api.py`** - API values endpoint
1. **`products/revenue_analytics/backend/hogql_queries/revenue_analytics_insights_query_runner.py`** - GroupBy implementation
1. **Database view files** (e.g., `revenue_analytics_customer_view.py`) - Ensure required fields exist
1. **Frontend component files** (e.g., `GrossRevenueTile.tsx`) - UI integration
1. **`frontend/src/lib/constants.tsx`** - Feature flag definition

The key pattern is that each new property needs to be defined at the schema level, mapped to database fields, integrated into the query building logic, and exposed through both filtering and groupBy interfaces.
