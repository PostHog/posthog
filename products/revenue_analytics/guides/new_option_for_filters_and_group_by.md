# How to add a new option for Revenue Analytics filters and group by

This guide explains all the steps required to add a new option that can be used both as a filter and as a group by (breakdown) option in Revenue Analytics. This is based on the implementation of the "country" option.

## Overview

Adding a new filter/breakdown option in Revenue Analytics only requires changes across three layers:

1. **Taxonomy system** - Define filter metadata for the UI
1. **Database view schema updates** - Ensure required fields are defined in the schema
1. **Database view updates** - Ensure required fields are available in the view definitions

## Step-by-Step Implementation

### 1. Taxonomy Definition

**File**: `posthog/taxonomy/taxonomy.py`

Add to the `CORE_FILTER_DEFINITIONS_BY_GROUP` under the `"revenue_analytics"` group making sure you include the proper prefix in the key:

```python
"revenue_analytics_customer.country": {
    "label": "Country",
    "description": "The country of the customer connected to the revenue event.",
    "type": "String",
    "virtual": True,
},
```

**Purpose**: Defines metadata for the filter that's used in the UI for labels, descriptions, and filter types.

**Important**: After updating this file, run `pnpm build:taxonomy` to generate the JSON file used by the frontend.

### 2. Database View Schema Updates

**File**: `products/revenue_analytics/backend/views/schema/customer.py`

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

**Purpose**: Ensures the database view schema includes all fields needed for the new property.

### 3. Database View Updates

**File**: `products/revenue_analytics/backend/views/sources/*/customer.py`

Ensure required fields are available in the view. This needs to be done for all sources:

```python
# Add to select fields in query generation
def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    # ... existing code ...
    select=[
        ast.Alias(alias="id", expr=ast.Field(chain=["outer", "id"])),
        ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
        ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),

        # ... existing code ...

        # These two were added
        ast.Alias(alias="address", expr=ast.Field(chain=["address"])),
        ast.Alias(alias="country", expr=ast.Call(name="JSONExtractString", args=[ast.Field(chain=["address"]), ast.Constant(value="country")])),
    ],
```

**Purpose**: Ensures the database view source includes all fields needed for the new property.

## Build Commands

After making the necessary changes, run these commands to regenerate the auto-generated files:

```bash
# After updating posthog/taxonomy/taxonomy.py
pnpm taxonomy:build

# After updating frontend/src/queries/schema/schema-general.ts
pnpm schema:build
```

## Summary of Files to Modify

When adding a new Revenue Analytics filter/breakdown option, you need to modify only these files:

1. **`posthog/taxonomy/taxonomy.py`** - Filter metadata definition
1. **Database view schema files** (e.g., `views/schema/*.py`) - Ensure required fields exist in the schema
1. **Database view source files** (e.g., `views/sources/**/*.py`) - Ensure required fields exist in the query source

The key pattern is that each new property needs to be defined at the schema level, mapped to database fields, integrated into the query building logic, and exposed through both filtering and groupBy interfaces.
