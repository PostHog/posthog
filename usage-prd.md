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

# In billing service
GET /api/usage-v2/            # For usage volumes
GET /api/usage-v2/spend/      # For calculated spend
```

#### Query Parameters (Usage Volume: `/api/usage-v2/`)
- `organization_id`: string (required)
- `start_date`: string (required, ISO format)
- `end_date`: string (required, ISO format)
- `usage_type`: string (optional) - specific usage type to query
- `breakdowns`: string (optional) - JSON array of breakdown dimensions (e.g., '["type"]', '["team"]', or '["type","team"]')
- `interval`: string (optional, default='day')
  - Supported values: 'day', 'week', 'month'
- `compare`: string (optional)
  - Supported values: 'previous_period'
- `show_values_on_series`: boolean (optional, default=false)

Note: When breaking down by 'type' (by including 'type' in the `breakdowns` parameter), the `usage_type` parameter is ignored as all types are returned.

#### Query Parameters (Spend: `/api/usage-v2/spend/`)
- `organization_id`: string (required)
- `start_date`: string (required, ISO format YYYY-MM-DD)
- `end_date`: string (required, ISO format YYYY-MM-DD)
- `breakdowns`: string (optional) - JSON array of breakdown dimensions (e.g. '["type"]', '["team"]', or '["type","team"]'). Omitting returns total spend.
- `interval`: string (optional, default='day')
  - Supported values: 'day', 'week', 'month'

#### Response Format (Usage Volume)
```typescript
interface UsageResponse {
    status: "ok";
    type: "timeseries";
    results: Array<{
        id: number;           // Unique identifier for the series
        label: string;        // Display name (e.g., "Events" or "Team A" or "Events::Team A")
        data: number[];       // Array of values
        dates: string[];      // Array of dates in ISO 8601 format (YYYY-MM-DD)
        breakdown_type: 'type' | 'team' | 'multiple' | null;  // What this series represents
        breakdown_value: string | string[] | null;            // Identifier for the breakdown dimension(s)
        compare_label?: string;            // For comparison periods
        count?: number;       // Total for percentage calculations
    }>;
    next?: string;  // Cursor for pagination if needed
}
```

#### Response Format (Spend: `/api/usage-v2/spend/`)

The spend endpoint returns data in the same time series format as the usage volume endpoint. The `results` array contains objects representing different series based on the requested breakdown.

```typescript
interface SpendResponse {
    status: "ok";
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

**Label Examples for Spend:**
- **No Breakdown:** `label: "Total Spend"`, `breakdown_type: null`, `breakdown_value: null`
- **Breakdown by Type:** `label: "Spend: Events"`, `breakdown_type: "type"`, `breakdown_value: "product_analytics"`
- **Breakdown by Team:** `label: "Team 123"`, `breakdown_type: "team"`, `breakdown_value: "123"`
- **Breakdown by Type & Team:** `label: "Spend: Events::Team 123"`, `breakdown_type: "multiple"`, `breakdown_value: ["product_analytics", "123"]`

### Multiple Breakdowns Support

The API supports breaking down usage data by one or more dimensions simultaneously using the `breakdowns` parameter, which accepts a JSON array of breakdown dimensions.

#### Examples:

1. No breakdown (total usage):
```
GET /api/usage-v2/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&usage_type=event_count_in_period
```

2. Single breakdown by type (all usage types):
```
GET /api/usage-v2/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&breakdowns=["type"]
```

3. Single breakdown by team:
```
GET /api/usage-v2/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&usage_type=event_count_in_period&breakdowns=["team"]
```

4. Multiple breakdowns (both type and team):
```
GET /api/usage-v2/?organization_id=123&start_date=2025-04-09&end_date=2025-04-16&breakdowns=["type","team"]
```

With multiple breakdowns, the `breakdown_value` field in the response will be an array containing values for each dimension, and labels will be formatted with a double-colon separator (e.g., "Events::Team 123").

#### SQL Implementation for Multiple Breakdowns

```sql
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
    AND date BETWEEN %s::date AND %s::date
)
SELECT 
    date,
    ARRAY[type, team_id] as breakdown_value,
    COALESCE(value, 0) as value
FROM team_usage
ORDER BY date, team_id, type
```

#### Authentication
- Requests from PostHog to the billing service will be authenticated using JWT tokens
- The billing service will validate that the requesting user is an owner or admin of the organization they're requesting data for
- PostHog will handle user authentication and authorization before proxying requests to the billing service

#### Data Flow

1. Database Query (in billing service):
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

2. Server Transformation (in billing service):
```python
# Example transformation from DB records to series format
def transform_to_timeseries_format(records: List[Dict]) -> List[Dict]:
    series_map = defaultdict(lambda: {"data": [], "dates": []})
    
    # Group by breakdown value (team or type)
    for record in sorted(records, key=lambda x: x["date"]):
        series = series_map[record["breakdown_value"]]
        series["data"].append(record["value"])
        series["dates"].append(record["date"].strftime("%Y-%m-%d"))  # Format dates as ISO 8601 (YYYY-MM-DD)
    
    # Convert to final format
    return [
        {
            "id": idx,
            "label": f"Team {breakdown_value}" if breakdown == "team" else breakdown_value,
            "data": series["data"],
            "dates": series["dates"],
            "breakdown_type": breakdown,
            "breakdown_value": breakdown_value,
        }
        for idx, (breakdown_value, series) in enumerate(series_map.items())
    ]

# Response will be pre-transformed series ready for LineGraph
return {
    "status": "ok",
    "type": "timeseries",
    "results": transform_to_timeseries_format(db_records)
}
```

3. PostHog API:
- Proxies request to billing service
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

The implementation consists of these core components:

1. **billingUsageLogic**: Kea logic for state management and API interaction
   - Uses shared default filter settings
   - Auto-loads data on mount
   - Manages filters, date ranges, and data fetching

2. **BillingLineGraph**: Chart.js-based visualization component (within `BillingUsage.tsx`)
   - Renders time-series data
   - Supports series toggling
   - Provides interactive tooltips

3. **LemonTable implementation**: Table view for detailed data
   - Shows values for all dates
   - Supports sorting by columns
   - Includes toggles for series visibility
   - Shows totals next to series names

4. **Filter Controls**: LemonUI components for data filtering
   - Usage type selector
   - Breakdown options
   - Date range picker
   - Interval selector
   - Compare toggle

### User Experience

- The interface shows both a line graph and a table below it
- The line graph provides a visual overview of the trends
- The table shows detailed values for every date point
- Users can toggle series visibility via checkboxes
- Filters update both the graph and table simultaneously
- The UI is consistent with PostHog's design system

## Implementation Guidelines

### Frontend Implementation

When modifying or extending the billing usage visualization:

1. **Continue with BillingUsage.tsx approach**:
   - Refer to this component as the canonical implementation
   - Extend this component rather than other variations
   - Maintain the direct Chart.js approach

2. **CSS and Styling**:
   - Follow the established pattern with a separate SCSS file (`BillingUsage.scss`)
   - Use CSS variables for colors
   - Leverage Tailwind classes where appropriate
   - Avoid inline styles

3. **State Management**:
   - Use billingUsageLogic for all data and filter state
   - Keep local state in React for UI-only concerns (like hiddenSeries)
   - Maintain the clear separation of logic and presentation

4. **Component Structure**:
   - Keep the BillingLineGraph as a separate component
   - Maintain the pattern of extracting complex rendering logic
   - Extract reusable helper functions and components

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
    usage_type: Optional[str] = None,
    breakdown: Optional[str] = None,
    interval: str = 'day',
    include_zeros: bool = True
) -> Dict[str, Any]:
    """
    Get usage data for the specified organization and parameters.
    
    Args:
        organization_id: The organization to query data for
        start_date: Beginning of date range 
        end_date: End of date range
        usage_type: Type of usage to query
        breakdown: How to break down results ('type', 'team', or None)
        interval: Time aggregation ('day', 'week', 'month')
        include_zeros: Whether to include zero values
        
    Returns:
        A dictionary with formatted time-series data
    """
    # Validate parameters
    if breakdown == 'type':
        # When breaking down by type, we ignore usage_type and fetch all types
        raw_data = get_usage_by_type(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date
        )
    elif breakdown == 'team':
        if usage_type:
            # Single usage type broken down by team
            raw_data = get_usage_by_team(
                organization_id=organization_id,
                start_date=start_date,
                end_date=end_date,
                usage_type=usage_type
            )
        else:
            # All usage types broken down by team
            raw_data = get_all_usage_by_team(
                organization_id=organization_id,
                start_date=start_date,
                end_date=end_date
            )
    else:
        # Single usage type for entire organization
        raw_data = get_base_usage(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            usage_type=usage_type
        )
    
    # Apply interval aggregation if needed
    if interval != 'day':
        raw_data = apply_interval_aggregation(raw_data, interval)
    
    # Filter out zeros if requested
    if not include_zeros:
        raw_data = [item for item in raw_data if item['value'] > 0]
    
    # Transform to time-series format expected by frontend
    result = transform_to_timeseries_format(raw_data, breakdown)
    
    return {
        "status": "ok",
        "type": "timeseries",
        "results": result
    }

# Helper functions to execute SQL queries
def execute_query(query: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Execute a raw SQL query and return results as a list of dictionaries."""
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

# Query functions
def get_base_usage(
    organization_id: str,
    start_date: date,
    end_date: date,
    usage_type: str
) -> List[Dict[str, Any]]:
    """Get usage data for a single metric across the entire organization."""
    query = """
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
            NULL as breakdown_value,
            COALESCE(value, 0) as value
        FROM daily_usage
        ORDER BY date
    """
    
    return execute_query(query, [usage_type, organization_id, start_date, end_date])

def get_usage_by_type(
    organization_id: str,
    start_date: date,
    end_date: date
) -> List[Dict[str, Any]]:
    """Get usage data broken down by usage type."""
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
    
    return execute_query(query, [SUPPORTED_USAGE_TYPES, organization_id, start_date, end_date])

# Additional query functions would be implemented for team breakdown and interval aggregation

# Transformation functions
def transform_to_timeseries_format(
    data: List[Dict[str, Any]],
    breakdown: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Transform raw data into time-series format for the frontend."""
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
        if breakdown == 'team':
            label = f"Team {breakdown_value}"
        
        result.append({
            "id": idx,
            "label": label,
            "data": series["data"],
            "dates": series["dates"],
            "breakdown_type": breakdown,
            "breakdown_value": breakdown_value if breakdown_value != 'total' else None
        })
        
    return result
```

## Service Architecture

The usage data functionality will be split between two repositories:

1. `posthog` repository:
   - Contains the API endpoints (`/api/billing/usage/`)
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
           
           # Pass raw params to billing service - parameter validation happens there
           billing_manager = BillingManager(...)
           return billing_manager.get_usage_data(
               organization=organization,
               params=request.GET
           )
   ```

2. `billing` repository:
   - Contains all billing-related business logic in services
   - Implements the actual database queries
   - Provides REST API endpoints for PostHog to consume
   - Includes parameter validation via serializers
   - Example endpoint: `GET /api/usage-v2/?organization_id=...`
   ```python
   class UsageV2Viewset(viewsets.ViewSet):
       def list(self, request):
           # Validate request parameters
           serializer = UsageRequestSerializer(data=request.GET)
           serializer.is_valid(raise_exception=True)
           
           # Pass validated data to service
           result = get_usage_data(**serializer.validated_data)
           return Response(result)
   ```

### Communication Flow
1. Client makes request to PostHog API (`/api/billing/usage/`)
2. PostHog validates request and auth
3. PostHog proxies to billing service (`/api/usage-v2/`) with auth token
4. Billing service executes queries and returns data
5. PostHog returns formatted response to client

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
```

2. Query Optimization:
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

- The endpoint `/api/usage-v2/spend` is implemented for querying monetary values, returning time-series data representing daily, weekly, or monthly spend.
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
- Parameters are `organization_id`, `start_date`, `end_date`, `breakdowns`, `interval`.

