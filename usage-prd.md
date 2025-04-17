# Usage Data API PRD

## Overview
This document outlines the requirements and implementation approach for the Usage Data API, which will provide time-series usage data from Postgres for visualization purposes.

## Requirements

### Data Sources
- Primary table: `billing_usagereport`
- Key columns:
  - `report` (JSONB): Contains both aggregated and team-level metrics
  - `date`: Daily timestamp for the data point
  - `organization_id`: Organization identifier

### Usage Types
Available usage types (from `report`):
- event_count_in_period
- exceptions_captured_in_period
- recording_count_in_period
- rows_synced_in_period
- survey_responses_count_in_period
- mobile_recording_count_in_period
- billable_feature_flag_requests_count_in_period
- enhanced_persons_event_count_in_period

These usage types are available both:
- At the top level for organization-wide totals
- Under `teams` object for team-specific breakdowns

### API Requirements

#### Endpoints
```python
# In posthog
GET /api/billing/usage/

# In billing service
GET /api/usage-v2/
```

#### Query Parameters
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

#### Response Format
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
        date::date,
        team_id::text,
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

The Usage Data UI will follow the same pattern as the existing Trends visualization, with a few specific customizations, and will be integrated into the existing Billing section rather than as a standalone page:

### Component Structure

1. **BillingUsage Component**: The existing component in the billing section will be enhanced
   - Will be rendered within the existing BillingSection.tsx when the usage tab is selected
   - Maintains consistent navigation and UI with the rest of the billing section
   - Reuses the existing URL structure (`/organization/billing/usage`)

2. **UsageVisualization**: Primary visualization component within BillingUsage
   - Adapts `ActionsLineGraph` pattern to usage data
   - Renders data using the LineGraph component
   - Supports both line and area chart types
   - Handles breakdown selections

3. **UsageTable**: Data table component
   - Displays the same data in tabular format
   - Shows each data point with precise values
   - Enables sorting by different columns

### Data Flow in Frontend

The frontend data flow will follow PostHog's standard practices:
- Use Kea logic for state management
- API calls through the PostHog API client
- Transform data only if needed (the API response is already in the correct format)
- Update UI components reactively based on state changes

### User Experience

- The interface will show both line graph and table
- Breakdown selector will offer options like "type" and "team" with multi-select capability
- Date range selector will use the existing date picker component
- Controls for showing/hiding specific series via legend

### Reused Components

The implementation will leverage several existing components:
- `LineGraph` for the primary visualization
- `InsightsTable` for the data table view
- Date range picker
- Dropdown selectors for filters
- LemonButton components for actions

## Implementation Guidelines

### Frontend Implementation

1. **Reference Existing Components**:
   - Study `trends/Trends.tsx` for overall layout and structure
   - Review `trends/viz/ActionsLineGraph.tsx` for how to hook up LineGraph
   - Examine `insights/views/LineGraph/LineGraph.tsx` for visualization options

2. **Kea Logic Implementation**:
   - Create `billingUsageLogic.ts` as the main state management
   - Define interfaces for API request/response data
   - Implement actions for loading data and updating filters
   - Set up selectors to prepare data for visualization
   - Add listeners to handle data fetching when filters change
   - Look at `trendsDataLogic.ts` for patterns to emulate

3. **Component Implementation Approach**:
   - Enhance `BillingUsage.tsx` to include filters and visualization
   - Create `UsageVisualization.tsx` for the actual chart render
   - Implement `UsageTable.tsx` for tabular representation
   - Follow PostHog UI patterns with LemonUI components

4. **Backend Integration**:
   - Add the `usage` action to `BillingViewset` in `ee/api/billing.py`
   - Implement a `proxy_request` method in `BillingManager` class
   - Ensure proper error handling and authentication

The implementation should favor simplicity, reuse of existing components, and adherence to PostHog's UI patterns. The design should be consistent with the rest of the application, particularly the billing section where it will be housed.

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

3. Planned Spend API Endpoint
- A new endpoint `/api/usage-v2/spend` is planned for querying monetary values
- Will support aggregation across usage types (unlike volumes endpoint)
- Will allow all combinations of breakdowns (total, by type, by team, and by both)
- Same time series format and parameter structure as the volumes endpoint
- Will have additional parameters for currency, pricing tiers, etc.
- Expected to be implemented once pricing data structure is available

