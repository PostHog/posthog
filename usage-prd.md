# Usage Data API PRD

## Overview
This document outlines the requirements and implementation approach for the Usage Data API, which will provide time-series usage data from Postgres for visualization purposes.

## Requirements

### Data Sources
- Primary table: `billing_usagereport`
- Key columns:
  - `date`: Daily timestamp for the data point
  - `organization_id`: Organization identifier
  - `reported_to_period_end`: Timestamp indicating when the current usage period ends
  - `report` (JSONB): Contains both aggregated and team-level metrics. Below are the key usage properties (partial list):
    ```json
    {
        "event_count_in_period": int,
        "exceptions_captured_in_period": int,
        "recording_count_in_period": int,
        "rows_synced_in_period": int,
        "survey_responses_count_in_period": int,
        "mobile_recording_count_in_period": int,
        "billable_feature_flag_requests_count_in_period": int,
        "enhanced_persons_event_count_in_period": int,
        "teams": {
            "$team_id": {
                // Same properties as above available per team
            }
        }
    }
    ```
  - `org_usage_summary` (JSONB): Daily aggregated usage metrics:
    ```json
    {
        "events": int,
        "exceptions": int,
        "recordings": int,
        "rows_synced": int,
        "survey_responses": int,
        "mobile_recordings": int,
        "feature_flag_requests": int,
        "enhanced_persons_events": int
    }
    ```
  - `usage_sent_to_stripe` (JSONB): Cumulative usage data for a billing period sent to Stripe:
    ```json
    {
        "product_analytics": int,
        "error_tracking": int,
        "session_replay": int,
        "data_warehouse": int,
        "surveys": int,
        "mobile_replay": int,
        "feature_flags": int,
        "enhanced_persons": int
    }
    ```
  - `custom_limits_map` (JSONB): Contains custom billing limits for specific features:
    ```json
    {
        "data_warehouse": int,    // Limit for rows_synced_in_period
        // ... other potential limits, same fields as in usage_sent_to_stripe
    }
    ```

#### Field Mappings

| report field                                  | org_usage_summary field  | usage_sent_to_stripe field |
|----------------------------------------------|-------------------------|--------------------------|
| event_count_in_period                        | events                 | product_analytics        |
| enhanced_persons_event_count_in_period      | enhanced_persons_events | enhanced_persons         |
| recording_count_in_period                    | recordings             | session_replay           |
| mobile_recording_count_in_period            | mobile_recordings      | mobile_replay            |
| rows_synced_in_period                       | rows_synced            | data_warehouse           |
| survey_responses_count_in_period            | survey_responses       | surveys                  |
| billable_feature_flag_requests_count_in_period | feature_flag_requests  | feature_flags            |
| exceptions_captured_in_period                | exceptions             | error_tracking           |

### API Requirements

#### Endpoints
```python
# In posthog
GET /api/billing/usage/
GET /api/billing/spend/

# In billing service (v2)
GET /api/v2/usage/            # For usage volumes
GET /api/v2/spend/            # For calculated spend
```

#### Query Parameters (Usage Volume: `/api/v2/usage/`)
- `organization_id`: string (required)
- `start_date`: string (required, ISO format)
- `end_date`: string (required, ISO format)
- `usage_types`: string (optional) - JSON array of usage type identifiers (e.g. `["event_count_in_period","recording_count_in_period"]`). If omitted or empty ⇒ all supported types (`SUPPORTED_USAGE_TYPES`). Default: *all types*.
- `team_ids`: string (optional) - JSON array of team IDs to include (e.g. `[123,456]`). If omitted or empty -> all teams considered (no team filtering applied). Default: *all teams*.
- `breakdowns`: string (optional) - JSON array of breakdown dimensions. Valid values: `[]` (or omitted), `["type"]`, `["type", "team"]`. Default: `["type"]` (effectively always breaking down by type).
- `interval`: string (optional, default='day')
  - Supported values: 'day', 'week', 'month'
- `teams_map`: string (optional) - JSON object string mapping team IDs (string) to team names (string). e.g. `'{"123": "Team A", "456": "Team B"}'`. Used for generating labels in the response.
- `compare`: string (optional) # Note: Not yet implemented

Note: Filters (`usage_types`, `team_ids`) apply regardless of the chosen breakdowns. You can, for instance, request a team breakdown limited to three specific teams (`team_ids=[1,2,3]`).

#### Query Parameters (Spend: `/api/v2/spend/`)
- `organization_id`: string (required)
- `start_date`: string (required, ISO format YYYY-MM-DD)
- `end_date`: string (required, ISO format YYYY-MM-DD)
- `usage_types`: string (optional) - JSON array of usage type identifiers to include. Default: *all types*.
- `team_ids`: string (optional) - JSON array of team IDs to include. Default: *all teams*.
- `breakdowns`: string (optional) - JSON array of breakdown dimensions (e.g. '["type"]', '["team"]', or '["type","team"]'). Omitting returns total spend.
- `interval`: string (optional, default='day')
  - Supported values: 'day', 'week', 'month'
- `teams_map`: string (optional) - JSON object string mapping team IDs (string) to team names (string). e.g. `'{"123": "Team A", "456": "Team B"}'`. Used for generating labels in the response.

Note: Filters (`usage_types`, `team_ids`) apply regardless of the chosen breakdowns. You can, for instance, request a team breakdown limited to three specific teams (`team_ids=[1,2,3]`).

#### Response Format (Usage Volume - V2)
```typescript
interface UsageResponse {
    status: "ok";
    customer_id: string;
    type: "timeseries";
    results: Array<{
        id: number;           // Unique identifier for the series
        label: string;        // Display name (e.g., "Events", "Team A (1)::Events", or "1::Events" if team name unknown)
        data: number[];       // Array of values
        dates: string[];      // Array of dates in ISO 8601 format (YYYY-MM-DD)
        breakdown_type: 'type' | 'multiple' | null; // 'type' if only type breakdown, 'multiple' if type+team breakdown.
        breakdown_value: string | string[] | null; // <usage_type> if breakdown_type is 'type', [<usage_type>, <team_id>] if breakdown_type is 'multiple'.
        compare_label?: string;            // For comparison periods
        count?: number;       // Total for percentage calculations (Note: Not currently implemented)
    }>;
    next?: string;  // Cursor for pagination if needed (Note: Not currently implemented)
}
```

#### Response Format (Spend - V2: `/api/v2/spend/`)

The spend endpoint returns data in the same time series format as the usage volume endpoint. The `results` array contains objects representing different series based on the requested breakdown.

```typescript
interface SpendResponse {
    status: "ok";
    customer_id: string;
    type: "timeseries";
    results: Array<{
        id: number;           // Unique identifier for the series
        label: string;        // Display name for the series (see examples below)
        data: number[];       // Array of calculated spend values (float, representing USD)
        dates: string[];      // Array of corresponding dates in ISO 8601 format (YYYY-MM-DD) for the start of the interval (day/week/month)
        breakdown_type: 'type' | 'team' | 'multiple' | null;  // Dimension(s) represented by this series
        breakdown_value: string | string[] | null;            // Identifier(s) for the breakdown dimension(s)
    }>;
}
```

**Label Examples for Spend (uses `teams_map` if provided):**
- **No Breakdown:** `label: "Total Spend"`, `breakdown_type: null`, `breakdown_value: null`
- **Breakdown by Type:** `label: "Events"`, `breakdown_type: "type"`, `breakdown_value: "product_analytics"` (Label uses `USAGE_TYPE_LABELS`)
- **Breakdown by Team:** `label: "Team A (123)"` or `label: "123"` (if name unknown), `breakdown_type: "team"`, `breakdown_value: "123"`
- **Breakdown by Type & Team:** `label: "Team A (123)::Events"` or `label: "123::Events"` (if name unknown), `breakdown_type: "multiple"`, `breakdown_value: ["product_analytics", "123"]`

### Multiple Breakdowns Support

The usage (not spend) API supports breaking down usage data by type (always) and optionally by team.

- **Default/Type Breakdown:** If `breakdowns` is omitted, `[]`, or `["type"]`, the API returns one series per filtered/supported `usage_type`.
  - `breakdown_type` will be `'type'`. 
  - `breakdown_value` will be the `<usage_type>` string.
- **Type and Team Breakdown:** If `breakdowns` is `["type", "team"]`, the API returns one series for each combination of filtered/supported `usage_type` and `team_id` present in the data.
  - `breakdown_type` will be `'multiple'`.
  - `breakdown_value` will be an array `[<usage_type>, <team_id>]`.


The spend API supports requests without any breakdowns (since aggregating totals across usage types makes sense) as well as any combination of `type` and `team`.

#### Examples (usage, not spend):

1. Breakdown by type (default - all types, all teams):
```
GET /api/v2/usage/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16
# Equivalent to: GET /api/v2/usage/?...&breakdowns=["type"]
```
Response will contain series like:
`{ ..., label: "Events", breakdown_type: "type", breakdown_value: "event_count_in_period" }`
`{ ..., label: "Recordings", breakdown_type: "type", breakdown_value: "recording_count_in_period" }`
...

2. Breakdown by type, filtered by specific types and teams:
```
GET /api/v2/usage/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&usage_types=["event_count_in_period","recording_count_in_period"]&team_ids=[1,2]
```
Response will contain series for Events and Recordings, but only including data from reports where team 1 or team 2 had *any* usage reported.
`{ ..., label: "Events", breakdown_type: "type", breakdown_value: "event_count_in_period" }`
`{ ..., label: "Recordings", breakdown_type: "type", breakdown_value: "recording_count_in_period" }`

3. Breakdown by type and team (all types, all teams, assumes `teams_map` provided):
```
GET /api/v2/usage/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&breakdowns=["type","team"]&teams_map='{"1": "Web", "2": "Mobile"}'
```
Response will contain series like:
`{ ..., label: "Web (1)::Events", breakdown_type: "multiple", breakdown_value: ["event_count_in_period", "1"] }`
`{ ..., label: "Web (1)::Recordings", breakdown_type: "multiple", breakdown_value: ["recording_count_in_period", "1"] }`
`{ ..., label: "Mobile (2)::Events", breakdown_type: "multiple", breakdown_value: ["event_count_in_period", "2"] }`
...
(If `teams_map` was not provided or a team ID was missing, labels would fall back to `1::Events`, `1::Recordings`, etc.)

4. Breakdown by type and team, filtered by specific types and teams:
```
GET /api/v2/usage/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&usage_types=["event_count_in_period"]&team_ids=[1]&breakdowns=["type","team"]&teams_map='{"1": "Web"}'
```
Response will contain series only for Events and only for team 1:
`{ ..., label: "Web (1)::Events", breakdown_type: "multiple", breakdown_value: ["event_count_in_period", "1"] }`


With multiple breakdowns, the `breakdown_value` field in the response will be an array containing values for each dimension, and labels will be formatted with a double-colon separator (e.g., "123::Events").

#### SQL Implementation for Multiple Breakdowns

```sql
-- Example SQL for breakdown by type, filtered by team_ids (if provided)
SELECT
    br.date::date,
    ut.type as usage_type,
    COALESCE((br.report->>ut.type)::numeric, 0) as value
FROM billing_usagereport br
CROSS JOIN unnest(%s::text[]) as ut(type) -- Takes list of usage_types or all
WHERE br.organization_id = %s
AND br.date BETWEEN %s::date AND %s::date
-- Optional filter:
AND EXISTS (
    SELECT 1
    FROM jsonb_object_keys(br.report->'teams') team_id
    WHERE team_id::text = ANY(%s::text[]) -- Takes list of team_ids
)
ORDER BY br.date, ut.type;

-- Example SQL for breakdown by type and team, filtered by usage_types and team_ids (if provided)
SELECT
    br.date::date,
    ut.type as usage_type,
    team_id::text,
    COALESCE((br.report->'teams'->team_id->>ut.type)::numeric, 0) as value
FROM billing_usagereport br
CROSS JOIN jsonb_object_keys(br.report->'teams') as team_id
CROSS JOIN unnest(%s::text[]) as ut(type) -- Takes list of usage_types (guaranteed non-empty)
WHERE br.organization_id = %s
AND br.date BETWEEN %s::date AND %s::date
-- Optional filter:
AND team_id::text = ANY(%s::text[]) -- Takes list of team_ids
ORDER BY br.date, ut.type, team_id;
```

#### Authentication
- Requests from PostHog to the billing service will be authenticated using JWT tokens
- The billing service will validate that the requesting user is an owner or admin of the organization they're requesting data for
- PostHog will handle user authentication and authorization before proxying requests to the billing service

#### Data Flow

1. Database Query (in billing service - via `UsageService` or `SpendService`)
```sql
-- Returns individual records
SELECT 
    date,
    team_id as breakdown_value,
    (report->'teams'->team_id->>%s)::numeric as value
FROM billing_usagereport
WHERE organization_id = %s 
AND date BETWEEN %s AND %s
ORDER BY date, team_id
```

2. Server Transformation (in billing service - via `UsageService` or `SpendService`)
```python
# Example transformation from DB records to series format
def transform_to_timeseries_format(
    data: List[Dict[str, Any]],
    breakdowns: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    interval: str = "day",
) -> List[Dict[str, Any]]:
    # ... (Implementation now handles flat list input) ...
    # ... (Groups data based on whether 'team' is in breakdowns) ...
    # ... (Applies interval aggregation) ...
    # ... (Pads dates and formats output) ...
    # Returns list of series dictionaries
    pass

# Response is constructed in get_usage_data:
return {
    "status": "ok",
    "type": "timeseries",
    "results": result_list # result_list from transform_to_timeseries_format
}
```

3. PostHog API (`/api/billing/usage/`, `/api/billing/spend/`):
   - Proxies request to billing service V2 endpoints (`/api/v2/usage/` or `/api/v2/spend/`)
- Returns transformed data directly to frontend
- No additional transformation needed

4. Frontend:
```typescript
// Data can be used directly with LineGraph component
<LineGraph
    datasets={response.results}
    labels={response.results[0]?.dates || []}
    type={GraphType.Line}
    isArea={true}
    // ... other LineGraph props
/>
```

This format:
- Aligns with existing LineGraph component requirements
- Minimizes client-side processing
- Supports all current and future visualization needs
- Keeps data transformation close to the data source
- Makes it easy to add features like comparisons later

## Frontend UI Implementation

After exploring several implementation approaches, we have decided to use a custom ChartJS-based approach as implemented in `BillingUsage.tsx` (originally `BillingUsage4.tsx`) as our primary frontend implementation going forward. The other experimental versions (`BillingUsage`, `BillingUsage2`, `BillingUsage3`, `BillingUsage5`) have been removed.

### Selected Implementation: BillingUsage (formerly BillingUsage4)

The `BillingUsage` component provides the best balance of simplicity, performance, and maintainability. It offers:

1. **Direct Chart.js integration**: Uses Chart.js without dependencies on insight systems
2. **Clean data flow**: Direct connection to billingUsageLogic
3. **Custom table view**: Shows all data points with proper formatting
4. **Series toggling**: Allows users to show/hide specific series
5. **Clean code structure**: Avoids architectural compromises and complex dependencies

This approach was chosen over alternatives that attempted to leverage the existing insight system, as it provides:
- Simpler architecture with fewer dependencies
- Better control over the visualization
- Improved performance with direct data flow
- Easier maintenance and extensibility

### Component Structure

The implementation now utilizes shared components for consistency:

1.  **`billingUsageLogic` / `billingSpendLogic`**: Kea logics for state management and API interaction.
    - Manage filter state (usage types, team IDs, breakdown, interval, compare, date range).
    - Handle API calls via loaders to fetch data (`/api/billing/usage/` or `/api/billing/spend/`).
    - Provide processed data (`series`, `dates`) to the UI via selectors.
    - Auto-load data on mount and when filters change.
2.  **`BillingLineGraph`**: A shared Chart.js-based visualization component (extracted from `BillingUsage`/`BillingSpendView`). Handles rendering time-series data, custom tooltips (sorted, custom style), and optional legend.
3.  **`BillingDataTable`**: A shared LemonTable-based component (extracted from `BillingUsage`/`BillingSpendView`). Handles displaying detailed series data, toggling visibility, default sorting by total, and series color indicators.
4.  **`BillingUsage` / `BillingSpendView`**: Parent components that connect to their respective Kea logic, orchestrate filters, and pass data/actions to the shared graph and table components.
5.  **Filter Controls**: LemonUI components for data filtering (Usage type, Breakdown, Date range, Interval, Compare).

### User Experience

- The interface shows both a line graph and a table below it
- The line graph provides a visual overview of the trends
- The table shows detailed values for every date point
- Users can toggle series visibility via checkboxes
- Filters update both the graph and table simultaneously
- The UI is consistent with PostHog's design system

#### Filter & Breakdown UX (2025-XX Update)

We now treat *break-down* and *filter-down* as orthogonal controls:

| Control | Type | Default | Notes |
|---------|------|---------|-------|
| **Break down by** | Checkbox list (`type`, `team`) | type only | Checking both == `["type", "team"]`. `type` is always implied (only in usage, not spend). | 
| **Usage types** | Multi-select tag list | all | Required if `team` breakdown checked. |
| **Teams** | Multi-select tag list (searchable) | all | — |

Client-side validation mirrors the backend rule above: volume view + team breakdown with zero selected usage types is blocked with inline error.

Request parameters sent: `breakdowns`, `usage_types`, `team_ids`.

## Implementation Guidelines

### Frontend Implementation

When modifying or extending the billing usage/spend visualization:

1.  **Utilize Shared Components**: Modifications to the graph or table should primarily happen within `BillingLineGraph.tsx` or `BillingDataTable.tsx`.
2.  **Parent Component Logic**: `BillingUsage.tsx` and `BillingSpendView.tsx` manage filters and integrate the shared components.
3.  **State Management**: All state related to filters and fetched data must reside within the corresponding Kea logic (`billingUsageLogic` or `billingSpendLogic`). Avoid local React state (`useState`) for data or filters.
4.  **CSS and Styling**:
    - Main styles are in `BillingUsage.scss` (used by both views currently).
    - Shared components use standard LemonUI/Tailwind patterns.

## Data Flow in Frontend

The frontend data flow follows PostHog's standard practices:
- Use billingUsageLogic for state management
- API calls through the PostHog API client
- Transform data in selectors if needed
- Update UI components reactively based on state changes

## Backend Implementation

The backend implementation remains as originally designed, providing flexible data access through the usage API:

1. **SQL Queries in Billing Service**: Efficient PostgreSQL queries using JSONB operations
2. **Parameter Validation**: Thorough parameter validation in serializers
3. **Service Layer**: Business logic and data transformations in service functions
4. **Proxy Endpoint in PostHog**: Forwarding requests to the billing service
5. **Authorization in PostHog**: Ensuring only organization owners/admins can access the data

## Implementation Notes

The implementation maintains a clear separation between frontend and backend concerns:
- Frontend focuses on visualization and user interaction
- Backend focuses on data access and transformation
- PostHog handles authorization and proxying
- Billing service handles the core business logic

This separation ensures maintainability and allows each layer to evolve independently.

## Implementation Approach

### SQL Queries

1. Base Usage Query (single type):
```sql
WITH daily_usage AS (
    SELECT 
        date,
        (report->>%s)::numeric as value
    FROM billing_usagereport
    WHERE organization_id = %s 
    AND date BETWEEN %s AND %s
)
SELECT 
    date,
    COALESCE(value, 0) as value
FROM daily_usage
ORDER BY date
```

2. Usage By Type Query:
```sql
WITH usage_data AS (
    SELECT 
        date,
        usage_type,
        (report->>usage_type)::numeric as value
    FROM billing_usagereport
    CROSS JOIN unnest(%s::text[]) as usage_type
    WHERE organization_id = %s 
    AND date BETWEEN %s AND %s
)
SELECT 
    date,
    usage_type as breakdown_value,
    COALESCE(value, 0) as value
FROM usage_data
ORDER BY date, usage_type
```

3. Usage By Team Query:
```sql
-- Single usage type per team
WITH team_usage AS (
    SELECT 
        date,
        team_id,
        (report->'teams'->team_id->>%s)::numeric as value
    FROM billing_usagereport
    CROSS JOIN jsonb_object_keys(report->'teams') as team_id
    WHERE organization_id = %s 
    AND date BETWEEN %s AND %s
)
SELECT 
    date,
    team_id as breakdown_value,
    COALESCE(value, 0) as value
FROM team_usage
ORDER BY date, team_id;

-- All usage types per team
WITH usage_types AS (
    SELECT unnest(%s::text[]) as type
),
team_usage AS (
    SELECT 
        date,
        team_id,
        type,
        (report->'teams'->team_id->>type)::numeric as value
    FROM billing_usagereport
    CROSS JOIN jsonb_object_keys(report->'teams') as team_id
    CROSS JOIN usage_types
    WHERE organization_id = %s 
    AND date BETWEEN %s AND %s
)
SELECT 
    date,
    team_id as breakdown_value,
    type as usage_type,
    COALESCE(value, 0) as value
FROM team_usage
WHERE value > 0  -- Skip zero values for performance
ORDER BY date DESC, team_id, type
```

4. Interval Aggregation (can be applied to any query above):
```sql
-- For weekly aggregation
SELECT 
    date_trunc('week', date) as period,
    breakdown_value,
    usage_type,  -- Only present in team + all usage types query
    sum(value) as value
FROM (...base query...) as daily_data
GROUP BY period, breakdown_value, usage_type
ORDER BY period, breakdown_value, usage_type

-- For monthly aggregation
SELECT 
    date_trunc('month', date) as period,
    breakdown_value,
    usage_type,  -- Only present in team + all usage types query
    sum(value) as value
FROM (...base query...) as daily_data
GROUP BY period, breakdown_value, usage_type
ORDER BY period, breakdown_value, usage_type
```

### Sample Query Results

For team breakdown with all usage types, results will look like:

| date | team_id | usage_type | value |
|------|---------|------------|-------|
| April 16, 2025 | 30393 | event_count_in_period | 5,925 |
| April 16, 2025 | 30393 | enhanced_persons_event_count_in_period | 5,756 |
| April 16, 2025 | 30393 | rows_synced_in_period | 38 |
| April 16, 2025 | 30393 | exceptions_captured_in_period | 4 |
| April 16, 2025 | 30393 | recording_count_in_period | 0 |
| April 16, 2025 | 33266 | event_count_in_period | 54,786 |
| April 16, 2025 | 33266 | enhanced_persons_event_count_in_period | 50,992 |
| April 16, 2025 | 33266 | rows_synced_in_period | 306,139 |
| April 15, 2025 | 30393 | event_count_in_period | 6,042 |
| April 15, 2025 | 30393 | enhanced_persons_event_count_in_period | 5,721 |

Notes about the format:
- Dates are in human-readable format
- Numbers are formatted with commas for readability
- Zero values are included (important for UI visualization)
- Results are ordered by date DESC, team_id, usage_type
- All usage types are shown for each team/date combination

### Python Implementation

Following the [HackSoft Django Styleguide](https://github.com/HackSoftware/Django-Styleguide), we'll implement the usage data functionality as service functions rather than using a repository pattern. This provides cleaner separation of concerns with lightweight API views and business logic in the service layer.

*(Note: SQL query parameters (`%s`) handle value injection prevention. Additional allowlist validation is applied in Python to parameters affecting SQL structure, like JSON keys or function arguments, before query construction.)*

```python
from datetime import date
from typing import List, Dict, Any, Optional
from django.db import connection

# Constants
SUPPORTED_USAGE_TYPES = [
    'event_count_in_period',
    'exceptions_captured_in_period',
    'recording_count_in_period',
    'rows_synced_in_period',
    'survey_responses_count_in_period',
    'mobile_recording_count_in_period',
    'billable_feature_flag_requests_count_in_period',
    'enhanced_persons_event_count_in_period'
]

# Core service function
def get_usage_data(
    organization_id: str,
    start_date: date,
    end_date: date,
    breakdowns: Optional[List[str]] = None,
    usage_types: Optional[List[str]] = None,
    team_ids: Optional[List[int]] = None,
    interval: str = "day",
) -> Dict[str, Any]:
    """
    Get usage data for the specified organization and parameters.
    
    Args:
        organization_id: The organization to query data for
        start_date: Beginning of date range 
        end_date: End of date range
        breakdowns: List of breakdown dimensions to apply
        usage_types: List of usage types to include
        team_ids: List of team IDs to include
        interval: Time aggregation ('day', 'week', 'month')
        
    Returns:
        A dictionary with formatted time-series data
    """
    # Validate parameters
    if breakdowns and "team" in breakdowns and not usage_types:
        raise ValueError("If 'team' is in breakdowns, 'usage_types' must be provided")
    
    is_team_breakdown = "team" in (breakdowns or [])

    if is_team_breakdown:
        raw_data = _fetch_usage_by_type_and_team(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            usage_types=usage_types,
            team_ids=team_ids
        )
    else:
        raw_data = _fetch_usage_by_type(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            usage_types=usage_types
        )
    
    # Apply interval aggregation if needed
    if interval != 'day':
        raw_data = apply_interval_aggregation(raw_data, interval)
    
    # Transform to time-series format expected by frontend
    result_list = transform_to_timeseries_format(
        data=raw_data,
        breakdowns=breakdowns,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )
    
    return {
        "status": "ok",
        "type": "timeseries",
        "results": result_list
    }

# Helper functions to execute SQL queries
def execute_query(query: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Execute a raw SQL query and return results as a list of dictionaries."""
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

# Refactored Query functions
def _fetch_usage_by_type(
    organization_id: str,
    start_date: date,
    end_date: date,
    usage_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetches usage data aggregated by type, applying filters."""
    query = """
        WITH usage_data AS (
            SELECT 
                date,
                usage_type,
                (report->>usage_type)::numeric as value
            FROM billing_usagereport
            CROSS JOIN unnest(%s::text[]) as usage_type
            WHERE organization_id = %s 
            AND date BETWEEN %s AND %s
        )
        SELECT 
            date,
            usage_type as breakdown_value,
            COALESCE(value, 0) as value
        FROM usage_data
        ORDER BY date, usage_type
    """
    
    return execute_query(query, [usage_types or SUPPORTED_USAGE_TYPES, organization_id, start_date, end_date])

def _fetch_usage_by_type_and_team(
    organization_id: str,
    start_date: date,
    end_date: date,
    usage_types: Optional[List[str]] = None,
    team_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Fetches usage data broken down by type and team, applying filters."""
    query = """
        SELECT
            br.date::date,
            ut.type as usage_type,
            COALESCE((br.report->>ut.type)::numeric, 0) as value
        FROM billing_usagereport br
        CROSS JOIN unnest(%s::text[]) as ut(type) -- Takes list of usage_types or all
        WHERE br.organization_id = %s
        AND br.date BETWEEN %s::date AND %s::date
        -- Optional filter:
        AND EXISTS (
            SELECT 1
            FROM jsonb_object_keys(br.report->'teams') team_id
            WHERE team_id::text = ANY(%s::text[]) -- Takes list of team_ids
        )
        ORDER BY br.date, ut.type;
    """
    
    return execute_query(query, [usage_types or SUPPORTED_USAGE_TYPES, organization_id, start_date, end_date, team_ids or []])

# Transformation functions
def transform_to_timeseries_format(
    data: List[Dict[str, Any]],
    breakdowns: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    interval: str = "day",
) -> List[Dict[str, Any]]:
    """Transform raw flat data into time-series format for the frontend."""
    series_map = {}
    
    for item in data:
        breakdown_value = item.get('breakdown_value', 'total')
        
        if breakdown_value not in series_map:
            series_map[breakdown_value] = {
                "data": [],
                "dates": []
            }
            
        series_map[breakdown_value]["data"].append(item['value'])
        series_map[breakdown_value]["dates"].append(
            item['date'].strftime("%Y-%m-%d") if hasattr(item['date'], 'strftime') else item['date']
        )
    
    result = []
    for idx, (breakdown_value, series) in enumerate(series_map.items()):
        label = breakdown_value
        if breakdowns and "team" in breakdowns:
            label = f"Team {breakdown_value}"
        
        result.append({
            "id": idx,
            "label": label,
            "data": series["data"],
            "dates": series["dates"],
            "breakdown_type": 'multiple' if breakdowns and "team" in breakdowns else 'type',
            "breakdown_value": breakdown_value if breakdowns and "team" not in breakdowns else None
        })
        
    return result

def apply_interval_aggregation(
    data: List[Dict[str, Any]],
    interval: str = "day",
) -> List[Dict[str, Any]]:
    """Apply interval aggregation to the given data."""
    if interval == 'day':
        return data
    
    # Implement interval aggregation logic based on the interval type
    # This is a placeholder and should be replaced with actual implementation
    return data
```

## Service Architecture

The usage data functionality will be split between two repositories:

1. `posthog` repository:
   - Contains the API endpoints (`/api/billing/usage/`, `/api/billing/spend/`)
   - Handles request validation and authentication
   - Uses `BillingManager` to proxy requests to billing service
   - Example:
   ```python
   class UsageViewSet(viewsets.ViewSet):
       def list(self, request):
           # Validate that the user is an owner or admin of the organization
           organization = request.user.organization
           if not organization.is_user_admin_or_owner(request.user):
               return Response(
                   {"detail": "You don't have permission to access this resource."},
                   status=status.HTTP_403_FORBIDDEN
               )
           
           # Pass raw params to billing service V2 endpoint - parameter validation happens there
           billing_manager = BillingManager(...)
           return billing_manager.get_usage_data(
               organization=organization,
               params=request.GET
           )
   ```

2. `billing` repository:
   - Contains all billing-related business logic in services (`UsageService`, `SpendService`)
   - Implements the actual database queries
   - Provides REST API V2 endpoints (`/api/v2/usage/`, `/api/v2/spend/`) for PostHog to consume
   - Includes parameter validation via V2 serializers
   - Example endpoint: `GET /api/v2/usage/?start_date=...`
   ```python
   @api_view(['GET'])
   @authentication_classes([JwtAuthentication]) # Example
   @permission_classes([]) # Example - Define actual permissions
   def usage(request):
       # Extract customer_id from auth/request (e.g., request.customer.id)
       customer_id = 'extracted_customer_id' # Placeholder
       
       # Validate request parameters using new V2 serializer location
       serializer = UsageRequestSerializer(data=request.query_params) # From billing.api.v2.serializers.usage
       serializer.is_valid(raise_exception=True)
       
       # Pass validated data to service class method
       try:
           # Instantiate service class (if not using static methods)
           usage_service = UsageService()
           result_dataclass = usage_service.get_usage_data(**serializer.validated_data)
       except Exception as e:
           # V2: Implement standardized error handling
           logger.error(f"Error fetching usage data for customer {customer_id}", exc_info=e)
           # Example standardized error response (adjust as needed)
           return Response(
               {"status": "error", "code": "USAGE_DATA_FETCH_FAILED", "message": "Failed to retrieve usage data."}, 
               status=status.HTTP_500_INTERNAL_SERVER_ERROR # Or appropriate status
           )

       # Instantiate V2 response serializer, passing the result dataclass and customer_id
       response_serializer = UsageResponseSerializer(instance=result_dataclass, context={'customer_id': customer_id})
       return Response(response_serializer.data)
   ```

### Communication Flow
1. Client makes request to PostHog API (`/api/billing/usage/` or `/api/billing/spend/`), potentially including the `teams_map` parameter.
2. PostHog validates request and auth.
3. PostHog proxies to billing service V2 endpoints (`/api/v2/usage/` or `/api/v2/spend/`) with auth token and all query parameters (including `teams_map`).
4. Billing service V2 view validates parameters using V2 Request Serializer (which validates `teams_map` into a dict).
5. Billing service V2 view calls corresponding Service Class (`UsageService` or `SpendService`), passing validated data (including the `teams_map` dict) via `**serializer.validated_data`.
6. Service Class executes queries and calls its transformation method, passing down the `teams_map`.
7. The transformation method uses the `teams_map` (if provided) to generate user-friendly labels for team-related breakdowns.
8. Service Class returns dataclass result.
9. Billing service V2 view constructs final response dictionary using V2 Response Serializer (adding `customer_id`, `status`, `type`).
10. Billing service returns JSON response.
11. PostHog returns formatted response to client.

### Rationale
- Billing service remains single source of truth for all billing data
- Consistent with existing billing service patterns
- Better separation of concerns
- Easier to maintain billing-specific security/compliance
- Changes to billing logic don't require PostHog deployment

---

*Note: All sections below are placeholders containing initial implementation details. They should be revisited and refined after the core functionality (queries, repository, and performance) is implemented - they should be ignored in the meantime.*

### Performance Considerations

1. Required Indexes:
```sql
CREATE INDEX billing_usage_org_date_idx ON billing_usagereport(organization_id, date);
CREATE INDEX billing_usage_report_idx ON billing_usagereport USING GIN (report);
```2. Query Optimization:
- All queries use CTEs for better readability and maintainability
- COALESCE handles null values consistently
- Indexes support efficient date range and organization filtering
- JSONB operations are optimized with GIN index

3. Caching Strategy:
```python
def get_cached_usage_data(organization_id: str, **params):
    cache_key = f"usage_data:{organization_id}:{hash(frozenset(params.items()))}"
    return cache.get_or_set(
        cache_key,
        lambda: usage_repository.get_usage_data(organization_id, **params),
        timeout=3600  # 1 hour cache
    )
```

### Error Handling
```python
class UsageAPIError(Exception):
    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code

def handle_usage_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UsageAPIError as e:
            return JsonResponse({
                'status': 'error',
                'message': e.message,
                'code': e.code
            }, status=e.status_code)
    return wrapper
```

## Testing Requirements

1. Unit Tests
- Test metric extraction logic
- Test interval aggregation
- Test team breakdown functionality
- Test error handling

2. Integration Tests
- Test with real Postgres instance
- Test cache behavior
- Test pagination
- Test with large datasets

3. Performance Tests
- Benchmark queries with different date ranges
- Benchmark queries with team breakdown
- Test cache hit ratios

## Monitoring

1. Metrics to Track
- Query execution time
- Cache hit ratio
- Error rates by type
- Usage patterns by metric/breakdown

2. Alerts
- Query time > 1s
- Error rate > 1%
- Cache hit ratio < 80%

## Migration Plan

1. Phase 1: Basic Implementation
- Implement base query functionality
- Add basic metric extraction
- Set up monitoring

2. Phase 2: Performance Optimization
- Add caching
- Optimize indexes
- Add pagination

3. Phase 3: Advanced Features
- Add team breakdown support
- Add interval aggregation
- Add comparison periods

## Future Considerations

1. Potential Optimizations
- Materialized views for common queries
- Pre-aggregated data for longer time ranges
- Parallel query execution for large datasets

2. Feature Extensions
- Additional breakdown dimensions
- Custom metric combinations
- Real-time data updates

3. Spend API Endpoint

- The endpoint `/api/v2/spend/` is implemented for querying monetary values, returning time-series data representing daily, weekly, or monthly spend.
- This endpoint provides insights into the monetary cost associated with product usage over time.
- It uses the cumulative `usage_sent_to_stripe` field from `billing_usagereport`.
- The calculation approach involves:
    - Fetching relevant `UsageReport` records using the Django ORM.
    - Fetching `stripe.Price` objects using `customer.get_product_to_price_map()`.
    - Iterating through the requested date range + 1 prior day.
    - Calculating daily spend per product type by determining the difference in cumulative cost between the current day and the last known valid cumulative cost baseline within the current billing period. The baseline is tracked and updated daily, resetting only on billing period changes (detected via `reported_to_period_end`). Cumulative cost is calculated using `usage_to_amount_usd` with the fetched prices and the cumulative usage from `usage_sent_to_stripe`.
    - Applying simple average smoothing: If `usage_sent_to_stripe` is missing or empty for one or more consecutive days, the spend calculated on the *next* day with data is averaged across the gap days (including the update day) to provide a smoother representation.
    - Aggregating the calculated (and potentially smoothed) daily spend based on the requested `interval`.
- Breakdowns supported:
    - Total (No Breakdown): Sums the calculated spend across all types for each interval period.
    - By Type: Returns a separate series for the calculated spend of each billable product type.
    - By Team: Calculates spend per type, allocates it proportionally to teams based on their volume contribution *for that specific type* within the interval, and then sums the allocated amounts per team across all types.
    - By Type & Team: Calculates spend per type and allocates it proportionally to teams based on their volume contribution *for that specific type* within the interval. Returns a series for each type/team combination.
- Parameters are `organization_id`, `start_date`, `end_date`, `usage_types`, `team_ids`, `breakdowns`, `interval`.

-## Best Practices Implemented
-
-1. **Function-based service pattern**: Clean separation of business logic from API views
-2. **Strongly typed interfaces**: Using type hints throughout for better code safety
-3. **Comprehensive input validation**: Detailed validation in serializers with clear error messages
-4. **Efficient SQL queries**: Direct use of PostgreSQL features like JSONB operations and arrays
-5. **Forward compatibility**: API design that allows adding new features without breaking changes
-6. **Consistent parameter naming**: Using only the `breakdowns` parameter for all breakdown needs
-7. **Thorough documentation**: Detailed docstrings and parameter descriptions
-
-## Notes
-- Following the HackSoft Django Styleguide service pattern
-- API views are as light as possible, delegating business logic to the service layer
-- Service functions are pure and focused on specific tasks
-- Most business logic lives in the service layer, not in API views or serializers
-- Services fetch from DB, perform transformations, and implement business rules
-- API views only validate inputs, call services, and return responses
-- PostHog only validates organization ownership, billing service handles all parameter validation