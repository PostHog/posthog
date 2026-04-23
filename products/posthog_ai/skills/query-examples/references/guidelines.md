### Querying data in PostHog

Use the `posthog:execute-sql` MCP tool to execute HogQL queries. HogQL is PostHog's variant of SQL that supports most of ClickHouse SQL. We use terms "HogQL" and "SQL" interchangeably. References mentioned in this file are relevant to PostHog's skill `query-examples`.

Do not assume that data exists. Use the SQL tool proactively to find the right data.

#### Search types

Proactively use different search types depending on a task:

- Grep-like (regex search) with `match()`, `LIKE`, `ILIKE`, `position`, `multiMatch`, etc.
- Full-text search with `hasToken`, `hasTokenCaseInsensitive`, etc. Make sure you pass string constants to `hasToken*` functions.
- Dumping results to a file and using bash commands to process potentially large outputs.

#### Data Groups

PostHog has two distinct groups of data you can query:

##### 1. System Data (PostHog-Created Data)

Data created directly in PostHog by users - metadata about PostHog setup.

All system tables are prefixed with `system.`:

Table | Description
`system.actions` | Named event combinations for filtering
`system.cohorts` | Groups of persons for segmentation
`system.dashboards` | Collections of insights
`system.data_warehouse_sources` | Connected external data sources
`system.data_warehouse_tables` | Connected tables with their columns and formats
`system.error_tracking_issues` | Error tracking issues (grouped exceptions)
`system.experiments` | A/B tests and experiments
`system.exports` | Export jobs
`system.feature_flags` | Feature flags for controlling rollouts
`system.groups` | Group entities
`system.ingestion_warnings` | Data ingestion issues
`system.insight_variables` | SQL, dashboard, and insight variables for dynamic query filtering
`system.insights` | Visual and textual representations of aggregated data
`system.logs_alerts` | Log alert configurations and their states
`system.logs_views` | Saved log filter views
`system.notebooks` | Collaborative documents with embedded insights
`system.surveys` | Questionnaires and feedback forms
`system.teams` | Team/project settings

**Example - List insights:**

```sql
SELECT id, name, short_id FROM system.insights WHERE NOT deleted LIMIT 10
```

**Example - Count insight variables:**

```sql
SELECT count() AS total FROM system.insight_variables
```

**System Models Reference**

Schema reference for PostHog's core system models, organized by domain:

- [Actions](references/models-actions.md)
- [Cohorts & Persons](references/models-cohorts.md)
- [Dashboards, Tiles & Insights](references/models-dashboards-insights.md)
- [Data Warehouse](references/models-data-warehouse.md)
- [Error Tracking](references/models-error-tracking.md)
- [Logs](references/models-logs.md)
- [Flags & Experiments](references/models-flags-experiments.md)
- [Notebooks](references/models-notebooks.md)
- [Surveys](references/models-surveys.md)
- [SQL Variables](references/models-variables.md)

**Entity Relationships**

From | Relation | To | Join
Experiment | 1:1 | FeatureFlag | `feature_flag_id`
Experiment | N:1 | Cohort | `exposure_cohort_id`
Survey | N:1 | FeatureFlag | `linked_flag_id`, `targeting_flag_id`
Survey | N:1 | Insight | `linked_insight_id`
Cohort | M:N | Person | via `cohortpeople`
Person | 1:N | PersonDistinctId | `person_id`

All entities are scoped by a team by default. You cannot access data of another team unless you switch a team.

##### 2. Captured Data (Analytics Data)

Data collected via the PostHog SDK - used for analytics.

Table | Description
`events` | Recorded events from SDKs
`persons` | Individuals captured by the SDK. "Person" = "user"
`groups` | Groups of individuals (organizations, companies, etc.)
`sessions` | Session data captured by the SDK
Data warehouse tables | Connected external data sources and custom views

Use `posthog:read-data-warehouse-schema` to retrieve the full schema of the tables above.

**Key concepts:**

- **Events**: Standardized events/properties start with `$` (e.g., `$pageview`). Custom ones start with any other character.
- **Properties**: Key-value metadata accessed via `properties.foo.bar` or `properties.foo['bar']` for special characters
- **Person properties**: Access via `events.person.properties.foo` or `persons.properties.foo`
- **Person property modes**: `person.properties.*` behavior depends on the project's person-on-events setting. Check the project metadata to determine if values are event-time (value at ingestion) or query-time (current value). See [Person property modes](references/person-property-modes.md) for details.
- **Unique users**: Use `events.person_id` for counting unique users

**Example - Weekly active users:**

```sql
SELECT toStartOfWeek(timestamp) AS week, count(DISTINCT person_id) AS users
FROM events
WHERE event = '$pageview'
  AND timestamp > now() - INTERVAL 8 WEEK
GROUP BY week
ORDER BY week DESC
```

##### 3. Document Embeddings (Semantic Search)

The `document_embeddings` table stores text content with vector embeddings, partitioned by `model_name`. To discover what kinds of data are available:

```sql
SELECT product, document_type, count() as cnt
FROM document_embeddings
WHERE model_name = 'text-embedding-3-small-1536'
  AND timestamp >= now() - INTERVAL 1 MONTH
GROUP BY product, document_type
ORDER BY cnt DESC
```

Run separately for each model. Available models: `'text-embedding-3-small-1536'`, `'text-embedding-3-large-3072'`. You MUST filter on exactly one `model_name` per query — it routes to the correct underlying ClickHouse table. `IN` clauses and cross-model queries will fail.

Use `embedText(text, model_name)` and `cosineDistance()` for semantic search. See the `signals` skill for detailed query patterns around the signals product specifically, including required deduplication and metadata extraction.

#### Querying guidelines

##### Schema verification

Before writing analytical queries, always verify that:

- The required event names or actions exist.
- Properties and property values of events, persons, sessions, and groups data exist.

Follow this workflow:

1. **Fetch the tool schema** - Use `posthog:read-data-schema` to get the latest schema from the MCP.
1. **Verify data exist** - Use `posthog:read-data-schema` with different data types to check if the data you need is captured
1. **Only then write the query** - Once you've confirmed the data exists, write and execute your analytical query

<example>
User: how many times the tool search was used?
Assistant:
1. First, verify the events exist:
   - Call `posthog:read-data-schema` with `kind: events`
   - Look for events/actions matching the request
2. If required events don't exist, inform the user immediately instead of running queries that will return empty results
3. If events exist, like "tool executed", verify the properties:
   - Call `posthog:read-data-schema` with `kind: event_properties` and `event_name: tool executed`
   - Look for properties indicating a tool
4. Check other events/actions or return if required properties don't exist
5. If events exist, like "tool_name", verify the property values:
   - Call `posthog:read-data-schema` with `kind: event_property_values`, `event_name: tool executed`, and `property_name: tool_name`
   - Follow the pattern from the sample or dig deeper into existing properties with SQL queries.
6. Only then write and execute the analytical SQL query

<reasoning>
Assistant should verify the data schema to write a correct SQL query, as the data schema varies over time.
</reasoning>
</example>

<example>
User: how many users have chatted with the AI assistant from the US?
Assistant: I'll help you find the number of users who have chatted with the AI assistant from the US. Let me create a todo list to track this implementation.
1. Find the relevant events to "chatted with the AI assistant"
2. Find the relevant properties of the events and persons to narrow down data to users from specific country
3. Retrieve the sample property values for found properties
4. Create the insight schema by using the data retrieved in the previous steps
5. Generate the insight
6. Analyze retrieved data
<reasoning>
The task list helps the assistant to stay on track.
</reasoning>
</example>

This prevents wasted API calls and gives users immediate feedback when the data they're looking for doesn't exist.

##### Skipping index

You should use the skipping index signature to write optimized analytical queries.

##### Time ranges

All analytical queries and subqueries must always have time ranges set for supported tables (events). If the user doesn't state it, assume default time range based on the data volume, like a day, week, or month.

**How you should use time ranges**

<example>
User: Find events from returning browsers - browsers that appeared both yesterday and today
Assistant:
```sql
SELECT event FROM events WHERE timestamp >= now() - INTERVAL 1 DAY and properties['$browser'] IN (SELECT properties['$browser'] FROM events WHERE timestamp >= now() - INTERVAL 2 DAY and timestamp < now() - INTERVAL 1 DAY)
```
</example>

**How you should NOT write queries**

<example>
User: List 10 events with SQL
Assistant:
```sql
SELECT event, timestamp, distinct_id, properties FROM events ORDER BY timestamp DESC LIMIT 10
```
</example>

##### JOINs

**General guidelines**

Keep in mind that the right expression is loaded in memory when joining data in ClickHouse, so the joining query or table must always fit in memory. Common strategies:

- Analytical functions and combinators.
- Subqueries as a source or filter.
- Arrays (arrayMap, arrayJoin) and ARRAY JOIN.

**System data**

You are allowed joining system data. Insights are the most used entity, so keep it on the left.

**Analytical data**

Prefer using analytical functions and subqueries for joins. Do not use raw joins on the events table.

**How you should join data**

<example>
User: Find ai traces with feedback
Assistant:
```sql
SELECT
 g.properties.$ai_trace_id as trace_id
FROM events AS g
WHERE
  timestamp >= now() - INTERVAL 1 WEEK
  AND g.event = '$ai_generation'
  AND trace_id IN (SELECT properties.$ai_trace_id FROM events WHERE event = '$ai_feedback' AND timestamp >= now() - INTERVAL 1 WEEK)
```
<reasoning>A subquery is used instead of a JOIN clause. Both queries have the timestamp filters.</reasoning>
</example>

**How you should NOT join data**

<example>
User: Find ai traces with feedback
Assistant:
```sql
SELECT
 g.properties.$ai_trace_id
FROM events AS g
INNER JOIN (SELECT properties.$ai_trace_id as trace_id FROM events WHERE event = '$ai_feedback') AS f
ON g.properties.$ai_trace_id = f.trace_id
WHERE g.event = '$ai_generation'
```
<reasoning>Join is not necessary here. The assistant could've used a subquery.</reasoning>
</example>

##### Other constraints

- Your query results are capped at 100 rows by default. You can request up to 500 rows using a LIMIT clause. If you need more data, paginate using LIMIT and OFFSET in subsequent queries.
- You should cherry-pick `properties` of events, persons, or groups, so we don't get OOMs. **Never select the full `properties` object** (e.g., `SELECT properties FROM events`) and dump it into the conversation output. Instead, select only the specific properties you need (e.g., `properties.$browser`, `properties.$os`). If you must inspect the full properties object, dump the query results to a file and use bash commands to explore it.
- When query results contain large JSON blobs (e.g., AI trace inputs/outputs, full property objects), always dump them to a file rather than outputting them directly. Use bash commands to process the file.

#### HogQL Differences from Standard SQL

##### Property access

```sql
-- Simple keys
properties.foo.bar

-- Keys with special characters
properties.foo['bar-baz']
```

##### Unsupported/changed functions

Don't use | Use instead
`toFloat64OrNull()`, `toFloat64()` | `toFloat()`
`toDateOrNull(timestamp)` | `toDate(timestamp)`
`LAG()`, `LEAD()` | `lagInFrame()`, `leadInFrame()` with `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`
`count(*)` | `count()`
`cardinality(bitmap)` | `bitmapCardinality(bitmap)`
`split()` | `splitByChar()`, `splitByString()`

##### JOIN constraints

Relational operators (`>`, `<`, `>=`, `<=`) are **forbidden** in JOIN clauses. Use CROSS JOIN with WHERE:

```sql
-- Wrong
JOIN persons p ON e.person_id = p.id AND e.timestamp > p.created_at

-- Correct
CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at
```

##### Syntax extensions and HogQL functions

Find the reference for [Sparkline, SemVer, Session replays, Actions, Translation, HTML tags and links, Text effects, and more](./references/hogql-extensions.md).

##### Other rules

- WHERE clause must come after all JOINs
- No semicolons at end of queries
- `toStartOfWeek(timestamp, 1)` for Monday start (numeric, not string)
- Always handle nulls before array functions: `splitByChar(',', coalesce(field, ''))`
- Performance: always filter `events` by timestamp

##### SQL Variables

Review the [reference](./references/models-variables.md) for SQL variables and dashboard filters.

##### Available HogQL functions

Verify what functions are available using [the reference list](./references/available-functions.md) with suitable bash commands.

#### Examples

**Weekly active users with activation event:**

```sql
SELECT week_of, countIf(weekly_event_count >= 3)
FROM (
   SELECT person.id AS person_id, toStartOfWeek(timestamp) AS week_of, count() AS weekly_event_count
   FROM events
   WHERE event = 'activation_event'
     AND properties.$current_url = 'https://example.com/foo/'
     AND toStartOfWeek(now()) - INTERVAL 8 WEEK <= timestamp
     AND timestamp < toStartOfWeek(now())
   GROUP BY person.id, week_of
)
GROUP BY week_of
ORDER BY week_of DESC
```

**Find cohorts by name:**

```sql
SELECT id, name, count FROM system.cohorts WHERE name ILIKE '%paying%' AND NOT deleted
```

**List feature flags:**

```sql
SELECT key, name, rollout_percentage
FROM system.feature_flags
WHERE NOT deleted
ORDER BY created_at DESC
LIMIT 20
```
