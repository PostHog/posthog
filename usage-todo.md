# Usage Data API Implementation Plan

## Overview
This document outlines the step-by-step implementation plan for the Usage Data API based on the requirements specified in `usage-prd.md`. The goal is to create a basic working version that can be queried as soon as possible, following the service pattern from the [HackSoft Django Styleguide](https://github.com/HackSoftware/Django-Styleguide).

## Phase 1: Basic Implementation

### Step 1: Set up the service layer ✅
- [x] Create a new file `billing/services/usage.py`
- [x] Define a function-based service `get_usage_data` that accepts parameters and fetches usage data
- [x] Implement a data transformation function `transform_to_timeseries_format` to format the results for API consumption
- [x] Create helper functions to build and execute the SQL queries
- [x] Add support for the base case (organization total for a single metric)
  - Implemented with `get_base_usage` function using raw SQL for efficient JSONB access
  - Added support for all usage types with `SUPPORTED_USAGE_TYPES` constant
  - Basic error handling and type safety with type hints

### Step 2: Create serializers for validation ✅
- [x] Create a file `billing/serializers/usage.py` for input and output serialization
- [x] Define a request serializer for validating query parameters
  - Added validation for all input parameters
  - Custom validation for date ranges
  - Parameter combination validation (e.g., breakdowns and usage_type)
- [x] Define a response serializer for standardizing the API output format
  - Created nested serializers for time series data points
  - Added date formatting to ISO strings
  - Full validation of response schema

### Step 3: Set up the API endpoint ✅
- [x] Create a new file `billing/api/usage_v2.py`
  - Implemented UsageV2ViewSet with list method
  - Added comprehensive error handling
  - Added detailed docstrings
- [x] Define the `UsageV2Viewset` class with a `list` method that validates inputs and calls the service
- [x] Register the endpoint in `billing/urls.py` as `/api/usage-v2/`
- [x] Use serializers for parameter validation
- [x] Pass validated parameters to the service layer

### Step 4: Basic Integration Testing
- [ ] Create a test file `billing/services/tests/test_usage.py` for service tests
- [ ] Create a test file `billing/api/tests/test_usage_v2.py` for API tests
- [ ] Write tests for the basic functionality
- [x] Manually test the endpoint with real data

## Phase 2: Adding Core Features

### Step 5: Implement single dimension breakdowns ✅
- [x] Add support for breaking down by usage type using the breakdowns parameter
- [x] Add support for breaking down by team using the breakdowns parameter
- [x] Update the transformation function to handle multiple series
- [ ] Add tests for the breakdown functionality

### Step 5.1: Add **filter-down** parameters (usage_types, team_ids) 🆕
- [ ] Extend query params and validation in `UsageRequestSerializer` (`usage_types`, `team_ids` – both JSON arrays)
- [ ] Update service layer functions to accept optional `usage_types` and `team_ids` and apply `WHERE` filters early in SQL.
- [ ] Add 400-error rule: if `breakdowns` includes "team" **and** `usage_types` is empty or not provided, return 400 (volume endpoint only).
- [ ] Mirror parameters for spend endpoint (no special validation rule required).

### Step 6: Implement multiple breakdowns ✅
- [x] Add a service function `get_usage_with_multiple_breakdowns` for breaking down by both team and type
- [x] Create a SQL query that returns data with array breakdown values
- [x] Update serializers to handle array breakdown values using JSONField
- [x] Implement a flexible `breakdowns` parameter that accepts a JSON array of dimensions
- [x] Add JSON validation for the breakdowns parameter
- [ ] Add tests for multiple breakdowns

### Step 7: Implement interval aggregation
- [ ] Add services to support 'day', 'week', and 'month' intervals
- [ ] Implement the date truncation logic
- [ ] Update the response transformation to handle different intervals
- [ ] Add tests for interval aggregation

### Step 8: Address API Design Improvements
- [x] Update parameter validation to make usage_type or breakdowns clearer
- [x] Consolidate on the `breakdowns` parameter only (remove `breakdown` parameter)
- [x] Improve error messages for invalid parameter combinations
- [ ] Add documentation for default behaviors
- [ ] Update code comments for clarity
- [ ] Ensure strict allowlist validation for parameters affecting SQL structure (e.g., `usage_type` keys, `interval` args) in addition to parameterization for values.

### Step 9: Add Authentication and Authorization
- [ ] Configure JWT authentication for the API endpoint
- [ ] Add organization ownership validation in the service layer
- [ ] Connect with the PostHog proxy endpoint

## Phase 3: PostHog Integration

### Step 10: Create PostHog API endpoint ✅
- [x] Implement `/api/billing/usage/` endpoint in PostHog
  - Added `usage` method to `BillingViewset` class
  - Requires admin/owner level access
  - Proxies requests to billing service
  - Handles errors consistently with other billing endpoints
- [x] Add user authentication and organization ownership validation
- [x] Pass raw query parameters to the billing service
- [x] Set up request proxying to the billing service (all parameter validation happens in billing)

### Step 11: Frontend Implementation ✅

After exploring multiple approaches, we've decided to standardize on the implementation originally in `BillingUsage4.tsx` as our canonical implementation. This component has been renamed to `BillingUsage.tsx`, and the other experimental versions (`BillingUsage.tsx` (original), `BillingUsage2.tsx`, `BillingUsage3.tsx`, `BillingUsage5.tsx`) have been removed.

### Step 11.1: New orthogonal filter UX (multi-selects) 🆕
- [x] Replace the single Usage-type `LemonSelect` with multi-select tag list.
- [x] Add Teams multi-select (searchable) fed by `/api/organizations/{id}/teams/` or preloaded.
- [x] Replace current breakdown dropdown with checkbox list.
- [x] Block apply if team breakdown with zero usage types in volume view.
- [x] Adjust Kea logic filters (`usage_types?: string[]`, `team_ids?: number[]`).
- [x] Ensure hidden-series toggling stays purely front-end and independent of filters.
- [ ] Clean up UI - alignment, shadows etc

### Step 12: Implement Default Filter Improvements ✅
- [x] Update billingUsageLogic to include default filters for:
  - [x] usage_type set to 'event_count_in_period'
  - [x] breakdowns set to ['team']
- [x] Ensure auto-loading of data with default filters on component mount

### Step 13: Complete BillingUsage Implementation
- [x] Refactored graph and table into shared `BillingLineGraph.tsx` and `BillingDataTable.tsx` components.
- [x] Implemented custom tooltip with sorting in `BillingLineGraph`.
- [x] Added default sorting and improved series display in `BillingDataTable`.
- [ ] Review and optimize BillingUsage implementation (formerly BillingUsage4)
- [ ] Ensure all needed features are properly implemented
- [ ] Clean up unnecessary code and optimize performance
- [ ] Add comprehensive tests for the BillingUsage component
- [ ] Update documentation to reflect the chosen implementation
- [x] Allow unselecting event types in the filter dropdown (show all types when none selected)

### Step 14: Frontend Enhancements
- [ ] Add option to normalize data (percentages) 
- [ ] Improve chart tooltips with more information
- [ ] Add filtering options to the table
- [ ] Add more granular team filtering options
- [ ] Add custom date range presets

## Future Improvements

### Additional query parameters
- [ ] Implement `compare` parameter for previous period comparison
- [ ] Add `show_values_on_series` parameter

### Performance optimizations
- [ ] Add caching for frequently requested data
- [ ] Optimize SQL queries for larger datasets
- [ ] Add pagination for large result sets

### Documentation improvements
- [ ] Enhance documentation for the `usage_type` parameter and its interaction with `breakdowns`
- [ ] Make default behavior more explicit in documentation
- [ ] Add examples for all parameter combinations

### Test coverage
- [ ] Add comprehensive test suite for all parameter combinations
- [ ] Add tests for edge cases and error conditions
- [ ] Add performance tests for large datasets

## Phase: Refactor Usage Data Fetching (Usage Endpoint Only)

### Step R1: Refactor Serializer (`UsageRequestSerializer`)
- [x] Replace `usage_type` field with `usage_types` (optional JSON array string).
- [x] Add `team_ids` field (optional JSON array string).
- [x] Keep `breakdowns` field (optional JSON array string).
- [x] Modify `validate` method:
    - [x] Parse `usage_types`, `team_ids`, `breakdowns` JSON strings into lists, overwriting original keys in `validated_data`.
    - [x] Validate `breakdowns` list allows only `None`, `[]`, `["type"]`, `["type", "team"]`.
    - [x] Implement 400 Rule: Error if `"team"` is in `validated_data['breakdowns']` and `validated_data['usage_types']` is empty/None.

### Step R2: Refactor Service Layer (`get_usage_data`)
- [x] Update signature to accept `usage_types: Optional[List[str]]`, `team_ids: Optional[List[int]]`, `breakdowns: Optional[List[str]]`.
- [x] Add routing logic: If `"team"` in `breakdowns`, call `_fetch_usage_by_type_and_team`; else call `_fetch_usage_by_type`. Pass filters.
- [x] Call `transform_to_timeseries_format` passing results and the original `breakdowns` list.

### Step R3: Implement Helper Functions (Separate Queries)
- [x] **`_fetch_usage_by_type`**:
    - [x] Create function accepting `usage_types`, `team_ids`.
    - [x] Implement SQL query: selects by type, filters by `usage_types`, applies `team_ids` filter via `WHERE EXISTS`.
    - [x] Return flat list (`date`, `usage_type`, `value`).
- [x] **`_fetch_usage_by_type_and_team`**:
    - [x] Create function accepting `usage_types`, `team_ids`.
    - [x] Implement SQL query: selects by type and team, filters by `usage_types`, applies `team_ids` filter via `AND team_id = ANY(...)`.
    - [x] Return flat list (`date`, `usage_type`, `team_id`, `value`).

### Step R4: Refactor Transformation (`transform_to_timeseries_format`)
- [x] Accept original `breakdowns` list as argument.
- [x] If `"team"` is in `breakdowns`: Group input by (`usage_type`, `team_id`), set `breakdown_type="multiple"`, `breakdown_value=[type, team_id]`.
- [x] Else: Group input by `usage_type`, set `breakdown_type="type"`, `breakdown_value=usage_type`.
- [x] Ensure date padding works correctly.
- [x] Handle interval aggregation within the transformation flow.

### Step R5: Update API View (`UsageV2ViewSet.list`)
- [x] Pass parsed `usage_types`, `team_ids`, and `breakdowns` list from `serializer.validated_data` to `get_usage_data`.

### Step R6: ~~Update Tests~~ (Skipped for now)
- ~~[ ] Adapt existing tests...~~
- ~~[ ] Add tests for new filter combinations...~~

## Phase: Refactor Spend Data Fetching (Spend Endpoint Only)

### Step S1: Refactor Serializer (`SpendRequestSerializer` in `billing/serializers/usage.py`) ✅
- [x] Add `usage_types` field (optional JSON array string, like Usage serializer).
- [x] Add `team_ids` field (optional JSON array string, like Usage serializer).
- [x] Update `breakdowns` field validation:
    - [x] Parse JSON string to list.
    - [x] Explicitly allow `[]` (empty list for total spend).
    - [x] Validate list items are only `'type'` or `'team'`.
    - [x] Normalize `['team', 'type']` to `['type', 'team']`.
    - [x] Default to `[]` if parameter is missing or null.
- [x] Update `validate` method:
    - [x] Parse and validate `usage_types` JSON -> `List[str]` (use stripe keys). Store parsed list/None back into `validated_data['usage_types']`.
    - [x] Parse and validate `team_ids` JSON -> `List[int]`. Store parsed list/None back into `validated_data['team_ids']`.
    - [x] Keep date validation (`start_date <= end_date`).
    - [x] Ensure NO 400 rule requiring `usage_types` when `breakdowns` includes `'team'`.

### Step S2: Refactor Service (`get_spend_data` in `billing/services/usage.py`) - Signature & Data Fetching ✅
- [x] Update function signature: `breakdowns_list: Optional[List[str]]`, add `usage_types: Optional[List[str]]`, `team_ids: Optional[List[int]]`.
- [x] Replace ORM query (`UsageReport.objects.filter`) with raw SQL:
    - [x] Fetch `date`, `usage_sent_to_stripe`, `report`, `reported_to_period_end` from `billing_usagereport`.
    - [x] Filter by `organization_id` and date range (`start_date - 1 day` to `end_date`).
    - [x] Order by `date`.
    - [x] Fetch results into a list of dictionaries.
- [x] Keep existing `customer` and `price_map` fetching logic.

### Step S3: Refactor Service (`get_spend_data`) - Calculation Logic Adaptation ✅
- [x] Adapt core daily spend calculation (`raw_daily_spend_by_type`) to iterate over SQL results (list of dicts) instead of ORM objects.
- [x] Keep logic for period resets, cumulative cost calculation (`usage_to_amount_usd`), deltas, and smoothing.
- [x] Keep interval aggregation logic (`aggregated_spend`), ensuring it stores `report` dicts needed for allocation.
- [x] Keep breakdown/allocation logic (`processed_data`), adapting it to use the `aggregated_spend` structure with SQL-fetched `report` dicts.

### Step S4: Refactor Service (`get_spend_data`) - Filtering Logic ✅
- [x] After calculating `processed_data` and before transformation:
    - [x] Add logic to filter `processed_data` dictionary based on `usage_types` and `team_ids` provided in the request, respecting the `breakdowns_list`:
        - [x] No filtering if `breakdowns_list` is `[]` (total).
        - [x] Filter by `usage_types` if `breakdowns_list` is `['type']`.
        - [x] Filter by `team_ids` (stringified) if `breakdowns_list` is `['team']`.
        - [x] Filter by both `usage_types` and `team_ids` (stringified) if `breakdowns_list` is `['type', 'team']`.

### Step S5: Refactor Service (`get_spend_data`) - Transformation ✅
- [x] Generate `all_period_starts` using `_generate_all_period_starts`.
- [x] Determine `final_breakdown_type` (`None`, `'type'`, `'team'`, `'multiple'`) from `breakdowns_list`.
- [x] Determine `breakdown_label_prefix` ("Total Spend", "Spend").
- [x] Call `_transform_spend_to_timeseries_format` with **filtered** `processed_data`, `final_breakdown_type`, `breakdown_label_prefix`, and `all_period_starts`.

### Step S6: Update API View (`SpendViewSet.list` in `billing/api/usage_v2.py`) ✅
- [x] Instantiate updated `SpendRequestSerializer`.
- [x] Update call to `get_spend_data`, passing:
    - [x] `breakdowns_list=validated_data.get('breakdowns', [])`
    - [x] `usage_types=validated_data.get('usage_types')`
    - [x] `team_ids=validated_data.get('team_ids')`
    - [x] Other params as before.

### Step S7: Verify Transformation Helper (`_transform_spend_to_timeseries_format` in `billing/services/usage.py`) ✅
- [x] Double-check (no code changes expected) that it correctly maps `breakdown_type` (`None`, `'type'`, `'team'`, `'multiple'`) to final `label` and `breakdown_value` (None, string, string, list) in the output.

### Step S8: Refactor Service (`get_spend_data`) - Revised Filtering/Aggregation ✅
- [x] **(S8.1) Always Allocate:** Modify breakdown logic to always calculate the most granular `(type, team)` allocation, regardless of `breakdowns_list`. Store this in a temporary variable (e.g., `allocated_data`).
- [x] **(S8.2) Filter Allocated Data:** Apply `usage_types` and `team_ids` filters directly to the `allocated_data` (based on the tuple keys).
- [x] **(S8.3) Aggregate Filtered Data:** Create the final `processed_data` by aggregating the `filtered_allocated_data` based on the original `breakdowns_list` requested by the user:
    - [x] If `breakdowns_list` is `["type", "team"]`: `processed_data = filtered_allocated_data`.
    - [x] If `breakdowns_list` is `["type"]`: Sum `filtered_allocated_data` values for each type key. (Ensure all expected keys exist).
    - [x] If `breakdowns_list` is `["team"]`: Sum `filtered_allocated_data` values for each team key.
    - [x] If `breakdowns_list` is `[]`: Sum all values in `filtered_allocated_data` into a single `"total"` key.
- [x] **(S8.4) Update Transformation Call:** Ensure the correct `final_breakdown_type` (corresponding to the original `breakdowns_list`) is passed to `_transform_spend_to_timeseries_format` along with the newly aggregated `processed_data`.

### Planned Spend API Endpoint

- [x] Define endpoint `/api/usage-v2/spend`.
- [x] Create `SpendRequestSerializer` and `SpendResponseSerializer`.
- [x] Implement `SpendViewSet` in `billing/api/usage_v2.py`.
- [x] Implement service function `get_spend_data` in `billing/services/usage.py`:
    - [x] Fetch required data (`date`, `usage_sent_to_stripe`, `report`, `reported_to_period_end`) including 1 day prior.
    - [x] Fetch `stripe.Price` objects using `customer.get_product_to_price_map()`.
    - [x] Calculate daily spend per type by diffing cumulative costs (using fetched prices and `usage_to_amount_usd`) considering billing period resets.
    - [x] Handle total spend aggregation.
    - [x] Apply simple average smoothing for days with missing/empty `usage_sent_to_stripe` data.
    - [x] Handle breakdown by type.
    - [x] Handle breakdown by team/type+team via proportional volume allocation based on `report['teams']`.
    - [x] Implement interval aggregation ('day', 'week', 'month').
    - [x] Adapt `transform_to_timeseries_format` for spend data (via `_transform_spend_to_timeseries_format` helper).
- [x] Register URL in `billing/urls.py`.
- [ ] Add unit tests for `get_spend_data` (tiers, resets, breakdowns, edge cases).
- [x] Update PostHog proxy if needed.

## Phase: Implement Separate Spend View

- [x] Create `billingSpendLogic.ts` based on `billingUsageLogic.ts`:
  - [x] Rename logic, paths, keys.
  - [x] Rename loader/action to `billingSpendResponse`/`loadBillingSpend`.
  - [x] Point loader to new `/api/billing/spend/` endpoint.
  - [x] Remove `usage_type` from filters and API params.
- [x] Create `BillingSpendView.tsx` based on `BillingUsage.tsx`:
  - [x] Use `billingSpendLogic`.
  - [x] Remove "Usage type" filter select.
  - [x] Remove usage type banner.
  - [x] Adapt graph rendering for currency formatting (Y-axis, tooltips).
  - [x] Adapt table rendering for currency formatting (cells, totals).
- [x] Add PostHog API endpoint (`ee/api/billing.py`):
  - [x] Add `@action` `spend` to `BillingViewset`.
  - [x] Implement auth checks.
  - [x] Call new `BillingManager.get_spend_data` to proxy to `/api/usage-v2/spend/`.
- [x] Add frontend route for `/billing/spend` pointing to `BillingSpendView`.
- [x] Add "Spend" tab to billing sub-navigation UI.

## Phase: Migrate to API v2 Structure

This phase migrates the existing usage and spend endpoints into the `/billing/api/v2/` structure, following its style guide with specific caveats.

### Step M1: Split and Prepare Service Files ✅
- [x] Create `billing/services/usage.py`.
- [x] Create `billing/services/spend.py`.
- [x] Create `billing/services/utils.py` (for shared constants, helpers, enums, dataclasses).

### Step M2: Refactor Services into Separate Files and Classes ✅
- [x] In `billing/services/utils.py`:
    - [x] Define shared Enums (`SupportedUsageType`, `IntervalEnum`, `StripeProductKey`, `BreakdownDimensionEnum`).
    - [x] Define shared constants (`ALL_SUPPORTED_USAGE_TYPES`, `USAGE_TYPE_LABELS`, `REPORT_TO_STRIPE_KEY_MAPPING`, `STRIPE_TO_REPORT_KEY_MAPPING`).
    - [x] Define shared helper functions (`_generate_all_period_starts`, `_apply_interval_aggregation`).
    - [x] Define shared service dataclasses (`TimeSeriesDataPoint`, `TimeSeriesResult`).
- [x] In `billing/services/usage.py`:
    - [x] Create a `UsageService` class.
    - [x] Implement the `get_usage_data` method using components from `utils.py`.
    - [x] Ensure the method returns the defined `TimeSeriesResult` dataclass.
    - [x] Move relevant helper functions into the class as private static methods.
- [x] In `billing/services/spend.py`:
    - [x] Create a `SpendService` class.
    - [x] Implement the `get_spend_data` method using components from `utils.py`.
    - [x] Ensure the method returns the defined `TimeSeriesResult` dataclass.
    - [x] Move relevant helper functions into the class as private static methods.

### Step M3: Move and Split Serializers ✅
- [x] Create directories: `billing/api/v2/serializers/usage/` and `billing/api/v2/serializers/spend/`.
- [x] Move `TimeSeriesDataPointSerializer` to `billing/api/v2/serializers/common.py`.
    - [x] Update `TimeSeriesDataPointSerializer` to serialize the `TimeSeriesDataPoint` dataclass.
- [x] Move `UsageRequestSerializer` and `UsageResponseSerializer` to `billing/api/v2/serializers/usage/usage.py`.
- [x] Move `SpendRequestSerializer` and `SpendResponseSerializer` to `billing/api/v2/serializers/spend/spend.py`.
- [x] Update `UsageResponseSerializer` and `SpendResponseSerializer`:
    - [x] Add `customer_id = serializers.CharField(read_only=True)` (handled via context).
    - [x] Ensure `status = serializers.CharField(read_only=True)` and `type = serializers.CharField(read_only=True)` are present.
    - [x] Ensure the `results` field serializes the `TimeSeriesResult.results` list using the updated `TimeSeriesDataPointSerializer(many=True)`.
- [x] Update `UsageRequestSerializer` and `SpendRequestSerializer`:
    - [x] Change `interval` field to use the `IntervalEnum`.
    - [x] Update validation logic for `usage_types` to use Enums (`SupportedUsageType`, `StripeProductKey`).
- [x] Delete the original `billing/serializers/usage.py` file.

### Step M4: Move and Refactor Views ✅
- [x] Create `billing/api/v2/views/usage.py`.
- [x] Create `billing/api/v2/views/spend.py`.
- [x] In `billing/api/v2/views/usage.py`, create `usage(request)` function-based view:
    - [x] Add decorators: `@api_view(['GET'])`, `@authentication_classes(...)`, `@permission_classes(...)` (placeholders added).
    - [x] Extract `customer_id` (placeholder added).
    - [x] Instantiate V2 `UsageRequestSerializer`.
    - [x] Instantiate `UsageService` and call `get_usage_data`.
    - [x] Implement standardized try/except block.
    - [x] Instantiate V2 `UsageResponseSerializer` with result dataclass and `customer_id` context.
    - [x] Return `Response(response_serializer.data)`.
- [x] In `billing/api/v2/views/spend.py`, create `spend(request)` function-based view similarly.
- [x] Delete the original `billing/api/usage_v2.py` file.

### Step M5: Update URL Configuration ✅
- [x] In `billing/api/v2/views/__init__.py`, import and expose `usage` and `spend` views.
- [x] In `billing/api/v2/urls.py`, add paths for `usage` and `spend`.
- [x] Include `billing.api.v2.urls` in main `billing/urls.py`.
- [x] Remove old `/api/usage-v2/` routes from `billing/urls.py`.

### Step M6: Verification & PostHog Adjustments ⏳
- [x] **PostHog Proxy (`BillingManager`):**
    - [x] Update `get_usage_data` method to call the **new** `/api/v2/usage/` endpoint in the billing service.
    - [x] Update `get_spend_data` method to call the **new** `/api/v2/spend/` endpoint in the billing service.
    - [x] Ensure correct parameters are passed.
    - [x] Verify handling of the V2 response structure (`status`, `customer_id`, `type`, `results`).
- [x] **Frontend (`billing*Logic.ts`):**
    - [x] Verify loaders (`loadBillingUsage`, `loadBillingSpend`) correctly call the PostHog proxy endpoints.
    - [x] Verify frontend logic correctly handles the V2 response format passed through the proxy.
- [ ] **Manual Testing:**
    - [ ] Manually test `/api/v2/usage/` and `/api/v2/spend/` via PostHog proxy.
    - [ ] Verify response structure and data accuracy in the frontend UI.
    - [ ] Verify standard error responses from the V2 endpoints.

### Step M7: Update Tests (Future)
- [ ] Adapt service tests for `UsageService` and `SpendService`. Move tests to `billing/services/tests/`.
- [ ] Adapt API tests for new V2 views/serializers. Move tests to `billing/api/v2/views/tests/`.