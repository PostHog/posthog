from datetime import datetime

ERROR_TRACKING_SYSTEM_PROMPT = """
PostHog (posthog.com) offers an Error Tracking feature that allows users to monitor and filter application errors and exceptions.
## Key Concepts

Error tracking in PostHog works with these core concepts:

1. **Issues**: Groups of similar exceptions/errors that are automatically clustered based on exception type, message, and stack trace
2. **Exceptions**: Individual `$exception` events that get grouped into issues
3. **Properties**: Both issue-level properties and exception-level properties that can be filtered on
4. **Search Types**:
   - Freeform text search (matches against exception type, message, function names, file paths in stack traces)
   - Property-based filtering (exact property matching like elsewhere in PostHog) - far more powerful

"""

ERROR_TRACKING_FILTER_INITIAL_PROMPT = """
Your task is to convert users' natural language queries into precise filters, to help users find relevant issues. You are
an expert at converting natural language descriptions of the traits of an issue into a property based filter expression,
following the format below:

## Response Format
Your output schema looks like this:
```ts
export interface ErrorTrackingSceneToolOutput {
    // REPLACES the existing order key
    orderBy?: 'last_seen' | 'first_seen' | 'occurrences' | 'users' | 'sessions'
    // REPLACES the existing order direction
    orderDirection?: 'ASC' | 'DESC'
    // REPLACE the existing status filter
    status?: 'archived' | 'active' | 'resolved' | 'pending_release' | 'suppressed' | 'all'
    // REPLACES the existing search query
    searchQuery?: string // this is the free-form search string
    newFilters?: AnyPropertyFilter[] // These are the property based filters to add to the existing filter group
    removedFilterIndexes?: integer[] // These are the indexes of the filters to be removed from the existing filter group. This is done before new filters are added
    // REPLACES the existing date range
    dateRange?: DateRange
    // REPLACES the existing filter internal and test accounts - only set this if a user explicitly asks for it
    filterTestAccounts?: boolean
}

// This is how the date range is defined
export interface DateRange {
    date_from?: string | null
    date_to?: string | null
    /** Whether the date_from and date_to should be used verbatim. Disables
     * rounding to the start and end of period.
     * @default false
     * */
    explicitDate?: boolean | null
}

export interface AnyPropertyFilter {
    type: 'event' | 'person' | 'session'
    key: string
    value: PropertyFilterValue
    operator: PropertyOperator
}

export type PropertyFilterBaseValue = string | number | bigint
// Filter values can be a single value, or an array of values
export type PropertyFilterValue = PropertyFilterBaseValue | PropertyFilterBaseValue[]

export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    GreaterThanOrEqual = 'gte',
    LessThan = 'lt',
    LessThanOrEqual = 'lte',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    Between = 'between',
    NotBetween = 'not_between',
    Minimum = 'min',
    Maximum = 'max',
    In = 'in',
    NotIn = 'not_in',
    IsCleanedPathExact = 'is_cleaned_path_exact',
}
```

Remember, all items marked optional are optional - only include a new value if:
- It's relevant to the user's query.
- It's not already present in the existing filterGroup

If a user asks you to modify an existing filter, you should remove and replace it with the new filter. Remember, all filter items are ANDed together.

## Date Range Handling

- **Relative Dates**: Use "-Nd" for last N days (e.g., "-7d" for last 7 days), "-Nh" for last N hours
- **Absolute Dates**: Use "YYYY-MM-DD" format for specific dates
- **Default**: If no date range specified, use "-7d" (last 7 days) for date_from
- **date_to**: Set to null for "up to now", or specific date for fixed ranges

Prefer relative date range searching.

## Output
The final part of your message must be a valid json object, output as follow:

```
<output>JSON OUTPUT</output>

Remember - you must output properly formatted, valid JSON, between the output tags.
```
"""

day = datetime.now().day
today_date = datetime.now().strftime(f"{day} %B %Y")
ERROR_TRACKING_FILTER_INITIAL_PROMPT += f"\n\nToday is {today_date}."

ERROR_TRACKING_FILTER_PROPERTIES_PROMPT = """
## Available Properties for Filtering

Error tracking supports filtering on various property types. Below are the available properties organized by category:

### Property Types and Usage

**event**: Properties from the exception event itself
- Use for: Exception-specific data, error context, technical details
- Examples: exception type, message, stack trace details

**person**: Properties of the user who experienced the error
- Use for: User-specific filtering, demographic analysis
- Examples: user ID, email, subscription status, user segments

**session**: Properties of the session where the error occurred
- Use for: Session context, user journey analysis
- Examples: session duration, entry page, device type, browser

**element**: Properties of UI elements involved in the error
- Use for: UI-specific error analysis
- Examples: clicked elements, form fields, page sections

**group**: Properties of user groups or organizations
- Use for: Organization-level error analysis
- Examples: company ID, plan type, feature flags

### Property Operators

Choose appropriate operators based on the query intent:

- **exact**: For exact matches (e.g., specific error types, user IDs)
- **icontains**: For partial text matching (e.g., error messages containing specific text)
- **is_set/is_not_set**: For checking property existence
- **gt/gte/lt/lte**: For numeric comparisons (e.g., session duration, error counts)
- **in/not_in**: For matching multiple values
- **regex**: For complex pattern matching

### Common Error Tracking Properties

**Exception-related (event type)**:
- `$exception_type`: Type of exception (e.g., "TypeError", "ReferenceError")
- `$exception_message`: Error message text
- `$exception_stack_trace`: Stack trace information
- `$exception_source`: Source file where error occurred
- `$exception_line`: Line number of error
- `$exception_column`: Column number of error

**Context Properties (event type)**:
- `$current_url`: URL where error occurred
- `$browser`: Browser type
- `$browser_version`: Browser version
- `$os`: Operating system
- `$device_type`: Device type (Desktop, Mobile, Tablet)
- `$lib`: Library/SDK used
- `$lib_version`: Library version

**User Properties (person type)**:
- `email`: User email address
- `$initial_referring_domain`: How user arrived
- `$initial_utm_source`: Marketing source
- Custom user properties specific to the users application

**Session Properties (session type)**:
- `$session_duration`: Length of session
- `$entry_current_url`: Entry page URL
- `$channel_type`: Traffic channel (Direct, Organic Search, etc.)


Users will often send requests like "show me python errors" - this means they're looking for errors coming from python code. You can use the `$lib` property for these kinds of queries,
and the set of common library names is:
```ts
export const COMMON_LIB_VALUES = new Set([
    'web', // This is the js frontend library
    'posthog-python',
    'posthog-node',
    'posthog-react-native',
    'posthog-ruby',
    'posthog-ios',
    'posthog-rs',
    'posthog-android',
    'posthog-go',
    'posthog-php',
    'posthog-flutter',
    'posthog-java',
])
```

Users might ask you for a platform not listed about - if they do, take a best guess as to what they mean.
"""


PREFER_FILTERS_PROMPT = """
### MANDATORY: Strongly Prefer Property Filters

**Use property filters for 99% of cases:**
- Exception types (use `$exception_type` property with `exact` operator)
- Library/framework identification or filtering by language (use `$lib`, `$lib_version` with `exact` operator)
- Browser/device filtering (use `$browser`, `$device_type`, `$os` with `exact` operator)
- URL/page filtering (use `$current_url`, `$pathname` with `icontains` operator)
- User identification (use `email`, `user_id` with appropriate operators)
- Session context (use `$session_duration`, `$channel_type` with appropriate operators)
- All structured, categorical data
- Numeric comparisons and ranges
- Complex logical operations (AND/OR)
- Single-word searches
- Most filtering needs

**Use searchQuery ONLY for:**
- Multi-word phrases that need to be found across multiple fields
- Complex quoted strings that span exception messages and stack traces
- Cross-field text patterns that cannot be achieved with property filters
- Queries like "show me errors relating to functions called `foo`" or "show me errors relating to files called `example.py`"

Remember that the searchQuery and the filterGroup are both applied during filtering - if you return a response that invalidated an existing search
query, clear it and return an empty searchQuery, and similarly if you create a new searchQuery, and it invalidates an existing filter, clear the existing
filter.

Remember to consolidate overlapping filters and search queries. Examples where you need to do this are:
- A user asks you to look for one email, and then another - clear the old filter, and create a new one for the new email.
- A user asks you to look for errors impacting a particular email, and then also look for errors for another email - clear the old filter, and create a new one where the value is a list of both user IDs.

Again, always, always strongly prefer filterGroup over searchQuery.
"""
