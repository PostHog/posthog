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

### Step 9: Add Authentication and Authorization
- [ ] Configure JWT authentication for the API endpoint
- [ ] Add organization ownership validation in the service layer
- [ ] Connect with the PostHog proxy endpoint

## Phase 3: PostHog Integration

### Step 10: Create PostHog API endpoint
- [ ] Implement `/api/billing/usage/` endpoint in PostHog
- [ ] Add user authentication and organization ownership validation
- [ ] Pass raw query parameters to the billing service
- [ ] Set up request proxying to the billing service (all parameter validation happens in billing)

### Step 11: Enhance BillingUsage Component
- [ ] Refactor the existing `BillingUsage.tsx` component
  - Implement usage data fetching logic in `billingUsageLogic.ts` 
  - Add state management for filters and visualizations
- [ ] Create visualization components for usage data
  - Implement a LineGraph-based visualization 
  - Reuse existing PostHog chart components
- [ ] Add necessary filter controls
  - Date range selection
  - Usage type and breakdown selectors
  - Chart type toggles

### Step 12: Complete Billing Usage UI
- [ ] Enhance the BillingUsage component with additional features
  - Multiple visualization options (line, area, bar charts)
  - Table view for raw data display
  - Export options for the data
- [ ] Implement testing for the frontend
  - Unit tests for logic and components
  - Integration tests for the complete UI flow
- [ ] Finalize UI styling and responsive design
  - Ensure consistent look with billing section
  - Proper error handling and loading states
  - Empty state displays

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

### Planned Spend API Endpoint
- [ ] Design a new `/api/usage-v2/spend` endpoint for querying monetary values
  - Will share similar structure as the volumes endpoint
  - Will support aggregation across usage types
  - Will need pricing data structure

## Best Practices Implemented

1. **Function-based service pattern**: Clean separation of business logic from API views
2. **Strongly typed interfaces**: Using type hints throughout for better code safety
3. **Comprehensive input validation**: Detailed validation in serializers with clear error messages
4. **Efficient SQL queries**: Direct use of PostgreSQL features like JSONB operations and arrays
5. **Forward compatibility**: API design that allows adding new features without breaking changes
6. **Consistent parameter naming**: Using only the `breakdowns` parameter for all breakdown needs
7. **Thorough documentation**: Detailed docstrings and parameter descriptions

## Notes
- Following the HackSoft Django Styleguide service pattern
- API views are as light as possible, delegating business logic to the service layer
- Service functions are pure and focused on specific tasks
- Most business logic lives in the service layer, not in API views or serializers
- Services fetch from DB, perform transformations, and implement business rules
- API views only validate inputs, call services, and return responses
- PostHog only validates organization ownership, billing service handles all parameter validation
