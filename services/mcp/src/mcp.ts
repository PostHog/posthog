import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { AnalyticsEvent, getPostHogClient } from '@/lib/analytics'
import { DurableObjectCache } from '@/lib/cache/DurableObjectCache'
import {
    CUSTOM_API_BASE_URL,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    toCloudRegion,
} from '@/lib/constants'
import { handleToolError } from '@/lib/errors'
import { formatResponse } from '@/lib/response'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import { getToolsFromContext } from '@/tools'
import type { CloudRegion, Context, State, Tool } from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

const SHARED_PROMPT = `
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

const INSTRUCTIONS_V1 = `
- You are a helpful assistant that can query PostHog API.
${SHARED_PROMPT}
`.trim()

const INSTRUCTIONS_V2 = `
- IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any PostHog tasks.
- The \`posthog-query-data\` skill is the root skill for all data retrieval tasks in PostHog. Read it first and then use the \`posthog:execute-sql\` tool to execute SQL queries.
${SHARED_PROMPT}

# Querying data in PostHog

Use the \`posthog:execute-sql\` MCP tool to execute HogQL queries. HogQL is PostHog's variant of SQL that supports most of ClickHouse SQL. We use terms "HogQL" and "SQL" interchangeably.

Do not assume that data exists. Use the SQL tool proactively to find the right data.

## Search types

Proactively use different search types depending on a task:

- Grep-like (regex search) with \`match()\`, \`LIKE\`, \`ILIKE\`, \`position\`, \`multiMatch\`, etc.
- Full-text search with \`hasToken\`, \`hasTokenCaseInsensitive\`, etc. Make sure you pass string constants to \`hasToken*\` functions.
- Dumping results to a file and using bash commands to process potentially large outputs.

## Data Groups

PostHog has two distinct groups of data you can query:

### 1. System Data (PostHog-Created Data)

Data created directly in PostHog by users - metadata about PostHog setup.

All system tables are prefixed with \`system.\`:

Table | Description
\`system.actions\` | Named event combinations for filtering
\`system.cohorts\` | Groups of persons for segmentation
\`system.dashboards\` | Collections of insights
\`system.data_warehouse_sources\` | Connected external data sources
\`system.data_warehouse_tables\` | Connected tables with their columns and formats
\`system.error_tracking_issues\` | Error tracking issues (grouped exceptions)
\`system.experiments\` | A/B tests and experiments
\`system.exports\` | Export jobs
\`system.feature_flags\` | Feature flags for controlling rollouts
\`system.groups\` | Group entities
\`system.group_type_mappings\` | Group type definitions
\`system.ingestion_warnings\` | Data ingestion issues
\`system.insight_variables\` | SQL, dashboard, and insight variables for dynamic query filtering
\`system.insights\` | Visual and textual representations of aggregated data
\`system.notebooks\` | Collaborative documents with embedded insights
\`system.surveys\` | Questionnaires and feedback forms
\`system.teams\` | Team/project settings

**Example - List insights:**

\`\`\`sql
SELECT id, name, short_id FROM system.insights WHERE NOT deleted LIMIT 10
\`\`\`

#### System Models Reference

Schema reference for PostHog's core system models, organized by domain:

- [Actions](references/models-actions.md)
- [Cohorts & Persons](references/models-cohorts.md)
- [Dashboards, Tiles & Insights](references/models-dashboards-insights.md)
- [Data Warehouse](references/models-data-warehouse.md)
- [Error Tracking](references/models-error-tracking.md)
- [Flags & Experiments](references/models-flags-experiments.md)
- [Groups](references/models-groups.md)
- [Notebooks](references/models-notebooks.md)
- [Surveys](references/models-surveys.md)
- [SQL Variables](references/models-variables.md)

#### Entity Relationships

From | Relation | To | Join
Experiment | 1:1 | FeatureFlag | \`feature_flag_id\`
Experiment | N:1 | Cohort | \`exposure_cohort_id\`
Survey | N:1 | FeatureFlag | \`linked_flag_id\`, \`targeting_flag_id\`
Survey | N:1 | Insight | \`linked_insight_id\`
Group | N:1 | GroupTypeMapping | \`group_type_index\` (logical)
Cohort | M:N | Person | via \`cohortpeople\`
Person | 1:N | PersonDistinctId | \`person_id\`

All entities are scoped by a team by default. You cannot access data of another team unless you switch a team.

### 2. Captured Data (Analytics Data)

Data collected via the PostHog SDK - used for analytics.

Table | Description
\`events\` | Recorded events from SDKs
\`persons\` | Individuals captured by the SDK. "Person" = "user"
\`groups\` | Groups of individuals (organizations, companies, etc.)
\`sessions\` | Session data captured by the SDK
Data warehouse tables | Connected external data sources and custom views

Use \`posthog:read-data-warehouse-schema\` to retrieve the full schema of the tables above.

**Key concepts:**

- **Events**: Standardized events/properties start with \`$\` (e.g., \`$pageview\`). Custom ones start with any other character.
- **Properties**: Key-value metadata accessed via \`properties.foo.bar\` or \`properties.foo['bar']\` for special characters
- **Person properties**: Access via \`events.person.properties.foo\` or \`persons.properties.foo\`
- **Unique users**: Use \`events.person_id\` for counting unique users

**Example - Weekly active users:**

\`\`\`sql
SELECT toStartOfWeek(timestamp) AS week, count(DISTINCT person_id) AS users
FROM events
WHERE event = '$pageview'
  AND timestamp > now() - INTERVAL 8 WEEK
GROUP BY week
ORDER BY week DESC
\`\`\`

## Querying guidelines

### Schema verification

Before writing analytical queries, always verify that:

- The required event names or actions exist.
- Properties and property values of events, persons, sessions, and groups data exist.

Follow this workflow:

1. **Fetch the tool schema** - Use \`posthog:read-data-schema\` to get the latest schema from the MCP.
1. **Verify data exist** - Use \`posthog:read-data-schema\` with different data types to check if the data you need is captured
1. **Only then write the query** - Once you've confirmed the data exists, write and execute your analytical query

<example>
User: Find AI traces with human feedback
Assistant:
1. First, verify the events exist:
   - Call \`posthog:read-data-schema\` with \`schema_type: "events"\`
   - Check if \`$ai_trace\`, \`$ai_generation\`, \`$ai_feedback\` events are in the results
2. If required events don't exist, inform the user immediately instead of running queries that will return empty results
3. If events exist, verify the properties:
   - Call \`posthog:read-data-schema\` with \`schema_type: "event_properties"\` and \`event_name: "$ai_trace"\`
   - Check if \`$ai_feedback\`, \`$ai_trace_id\` properties exist
4. Only then execute the analytical query
</example>

This prevents wasted API calls and gives users immediate feedback when the data they're looking for doesn't exist.

### Skipping index

You should use the skipping index signature to write optimized analytical queries.

### Time ranges

All analytical queries and subqueries must always have time ranges set for supported tables (events). If the user doesn't state it, assume default time range based on the data volume, like a day, week, or month.

#### How you should use time ranges

<example>
User: Find events from returning browsers - browsers that appeared both yesterday and today
Assistant:
\`\`\`sql
SELECT event FROM events WHERE timestamp >= now() - INTERVAL 1 DAY and properties['$browser'] IN (SELECT properties['$browser'] FROM events WHERE timestamp >= now() - INTERVAL 2 DAY and timestamp < now() - INTERVAL 1 DAY)
\`\`\`
</example>

#### How you should NOT write queries

<example>
User: List 10 events with SQL
Assistant:
\`\`\`sql
SELECT event, timestamp, distinct_id, properties FROM events ORDER BY timestamp DESC LIMIT 10
\`\`\`
</example>

### JOINs

#### General guidelines

Keep in mind that the right expression is loaded in memory when joining data in ClickHouse, so the joining query or table must always fit in memory. Common strategies:

- Analytical functions and combinators.
- Subqueries as a source or filter.
- Arrays (arrayMap, arrayJoin) and ARRAY JOIN.

#### System data

You are allowed joining system data. Insights are the most used entity, so keep it on the left.

#### Analytical data

Prefer using analytical functions and subqueries for joins. Do not use raw joins on the events table.

##### How you should join data

<example>
User: Find ai traces with feedback
Assistant:
\`\`\`sql
SELECT
 g.properties.$ai_trace_id as trace_id
FROM events AS g
WHERE
  timestamp >= now() - INTERVAL 1 WEEK
  AND g.event = '$ai_generation'
  AND trace_id IN (SELECT properties.$ai_trace_id FROM events WHERE event = '$ai_feedback' AND timestamp >= now() - INTERVAL 1 WEEK)
\`\`\`
<reasoning>A subquery is used instead of a JOIN clause. Both queries have the timestamp filters.</reasoning>
</example>

##### How you should NOT join data

<example>
User: Find ai traces with feedback
Assistant:
\`\`\`sql
SELECT
 g.properties.$ai_trace_id
FROM events AS g
INNER JOIN (SELECT properties.$ai_trace_id as trace_id FROM events WHERE event = '$ai_feedback') AS f
ON g.properties.$ai_trace_id = f.trace_id
WHERE g.event = '$ai_generation'
\`\`\`
<reasoning>Join is not necessary here. The assistant could've used a subquery.</reasoning>
</example>

### Other constraints

- Your query results are capped at 100 rows by default. You can request up to 500 rows using a LIMIT clause. If you need more data, paginate using LIMIT and OFFSET in subsequent queries.
- You should cherry-pick \`properties\` of events, persons, or groups, so we don't get OOMs.

---

## HogQL Differences from Standard SQL

### Property access

\`\`\`sql
-- Simple keys
properties.foo.bar

-- Keys with special characters
properties.foo['bar-baz']
\`\`\`

### Unsupported/changed functions

Don't use | Use instead
\`toFloat64OrNull()\`, \`toFloat64()\` | \`toFloat()\`
\`toDateOrNull(timestamp)\` | \`toDate(timestamp)\`
\`LAG()\`, \`LEAD()\` | \`lagInFrame()\`, \`leadInFrame()\` with \`ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING\`
\`count(*)\` | \`count()\`
\`cardinality(bitmap)\` | \`bitmapCardinality(bitmap)\`
\`split()\` | \`splitByChar()\`, \`splitByString()\`

### JOIN constraints

Relational operators (\`>\`, \`<\`, \`>=\`, \`<=\`) are **forbidden** in JOIN clauses. Use CROSS JOIN with WHERE:

\`\`\`sql
-- Wrong
JOIN persons p ON e.person_id = p.id AND e.timestamp > p.created_at

-- Correct
CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at
\`\`\`

### Syntax extensions and HogQL functions

Find the reference for [Sparkline, SemVer, Session replays, Actions, Translation, HTML tags and links, Text effects, and more](./references/hogql-extensions.md).

### Other rules

- WHERE clause must come after all JOINs
- No semicolons at end of queries
- \`toStartOfWeek(timestamp, 1)\` for Monday start (numeric, not string)
- Always handle nulls before array functions: \`splitByChar(',', coalesce(field, ''))\`
- Performance: always filter \`events\` by timestamp

### SQL Variables

Review the [reference](./references/models-variables.md) for SQL variables and dashboard filters.

### Available HogQL functions

Verify what functions are available using [the reference list](./references/available-functions.md) with suitable bash commands.

---

## Examples

**Weekly active users with activation event:**

\`\`\`sql
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
\`\`\`

**Find cohorts by name:**

\`\`\`sql
SELECT id, name, count FROM system.cohorts WHERE name ILIKE '%paying%' AND NOT deleted
\`\`\`

**List feature flags:**

\`\`\`sql
SELECT key, name, rollout_percentage
FROM system.feature_flags
WHERE NOT deleted
ORDER BY created_at DESC
LIMIT 20
\`\`\`

## Examples reference

Use the examples below to create optimized queries.

- [Trends (unique users, specific time range, single series)](./references/example-trends-unique-users.md)
- [Trends (total count with multiple breakdowns)](./references/example-trends-breakdowns.md)
- [Funnel (two steps, aggregated by unique users, broken down by the person's role, sequential, 14-day conversion window)](./references/example-funnel-breakdown.md)
- [Conversion trends (funnel, two steps, aggregated by unique groups, 1-day conversion window)](./references/example-funnel-trends.md)
- [Retention (unique users, returned to perform an event in the next 12 weeks, recurring)](./references/example-retention.md)
- [User paths (pageviews, three steps, applied path cleaning and filters, maximum 50 paths)](./references/example-paths.md)
- [Lifecycle (unique users by pageviews)](./references/example-lifecycle.md)
- [Stickiness (counted by pageviews from unique users, defined by at least one event for the interval, non-cumulative)](./references/example-stickiness.md)
- [LLM trace (generations, spans, embeddings, human feedback, captured AI metrics)](./references/example-llm-trace.md)
- [Web path stats (paths, visitors, views, bounce rate)](./references/example-web-path-stats.md)
- [Web traffic channels (direct, organic search, etc)](./references/example-web-traffic-channels.md)
- [Web views by devices](./references/example-web-traffic-by-device-type.md)
- [Web overview](./references/example-web-overview.md)
- [Error tracking (search for a value in an error and filtering by custom properties)](./references/example-error-tracking.md)
- [Logs (filtering by severity and searching for a term)](./references/example-logs.md)
- [Sessions (listing sessions with duration, pageviews, and bounce rate)](./references/example-sessions.md)
- [Session replay (listing recordings with activity filters)](./references/example-session-replay.md)

`.trim()

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
    region?: string
    version?: number
    organizationId?: string
    projectId?: string
}

export class MCP extends McpAgent<Env> {
    server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions: INSTRUCTIONS_V1 })

    initialState: State = {
        projectId: undefined,
        orgId: undefined,
        distinctId: undefined,
        region: undefined,
        apiKey: undefined,
    }

    _cache: DurableObjectCache<State> | undefined

    _api: ApiClient | undefined

    _sessionManager: SessionManager | undefined

    get requestProperties(): RequestProperties {
        return this.props as RequestProperties
    }

    get cache(): DurableObjectCache<State> {
        if (!this.requestProperties.userHash) {
            throw new Error('User hash is required to use the cache')
        }

        if (!this._cache) {
            this._cache = new DurableObjectCache<State>(this.requestProperties.userHash, this.ctx.storage)
        }

        return this._cache
    }

    get sessionManager(): SessionManager {
        if (!this._sessionManager) {
            this._sessionManager = new SessionManager(this.cache)
        }

        return this._sessionManager
    }

    async detectRegion(): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: POSTHOG_US_BASE_URL,
        })

        const euClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: POSTHOG_EU_BASE_URL,
        })

        const [usResult, euResult] = await Promise.all([usClient.users().me(), euClient.users().me()])

        if (usResult.success) {
            await this.cache.set('region', 'us')
            return 'us'
        }

        if (euResult.success) {
            await this.cache.set('region', 'eu')
            return 'eu'
        }

        return undefined
    }

    async getBaseUrl(): Promise<string> {
        if (CUSTOM_API_BASE_URL) {
            return CUSTOM_API_BASE_URL
        }

        // Check region from request props first (passed via URL param), then cache, then detect
        const propsRegion = this.requestProperties.region
        if (propsRegion) {
            const region = toCloudRegion(propsRegion)
            // Cache it for future requests
            await this.cache.set('region', region)
            return getBaseUrlForRegion(region)
        }

        const cachedRegion = await this.cache.get('region')
        const region = cachedRegion ? toCloudRegion(cachedRegion) : await this.detectRegion()

        return getBaseUrlForRegion(region || 'us')
    }

    async api(): Promise<ApiClient> {
        if (!this._api) {
            const baseUrl = await this.getBaseUrl()
            this._api = new ApiClient({
                apiToken: this.requestProperties.apiToken,
                baseUrl,
            })
        }

        return this._api
    }

    async getDistinctId(): Promise<string> {
        let _distinctId = await this.cache.get('distinctId')

        if (!_distinctId) {
            const userResult = await (await this.api()).users().me()
            if (!userResult.success) {
                throw new Error(`Failed to get user: ${userResult.error.message}`)
            }
            await this.cache.set('distinctId', userResult.data.distinct_id)
            _distinctId = userResult.data.distinct_id as string
        }

        return _distinctId
    }

    async trackEvent(event: AnalyticsEvent, properties: Record<string, any> = {}): Promise<void> {
        try {
            const distinctId = await this.getDistinctId()

            const client = getPostHogClient()

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(this.requestProperties.sessionId
                        ? {
                              $session_id: await this.sessionManager.getSessionUuid(this.requestProperties.sessionId),
                          }
                        : {}),
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }

    registerTool<TSchema extends z.ZodRawShape>(
        tool: Tool<z.ZodObject<TSchema>>,
        handler: (params: z.infer<z.ZodObject<TSchema>>) => Promise<any>
    ): void {
        const wrappedHandler = async (params: z.infer<z.ZodObject<TSchema>>): Promise<any> => {
            const validation = tool.schema.safeParse(params)

            if (!validation.success) {
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                    tool: tool.name,
                    valid_input: false,
                    input: params,
                })
                return [
                    {
                        type: 'text',
                        text: `Invalid input: ${validation.error.message}`,
                    },
                ]
            }

            await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                tool: tool.name,
                valid_input: true,
            })

            try {
                const result = await handler(params)
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_RESPONSE, { tool: tool.name })

                // For tools with UI resources, include structuredContent for better UI rendering
                // structuredContent is not added to model context, only used by UI apps
                const hasUiResource = tool._meta?.ui?.resourceUri

                // If there's a UI resource, include analytics metadata for the UI app
                // The structuredContent is typed as WithAnalytics<T> where T is the tool result
                let structuredContent: WithAnalytics<typeof result> | typeof result = result
                if (hasUiResource) {
                    const distinctId = await this.getDistinctId()
                    const analyticsMetadata: AnalyticsMetadata = {
                        distinctId,
                        toolName: tool.name,
                    }
                    structuredContent = {
                        ...result,
                        _analytics: analyticsMetadata,
                    }
                }

                return {
                    content: [
                        {
                            type: 'text',
                            text: formatResponse(result),
                        },
                    ],
                    // Include raw result as structuredContent for UI apps to consume
                    ...(hasUiResource ? { structuredContent } : {}),
                }
            } catch (error: any) {
                const distinctId = await this.getDistinctId()
                return handleToolError(
                    error,
                    tool.name,
                    distinctId,
                    this.requestProperties.sessionId
                        ? await this.sessionManager.getSessionUuid(this.requestProperties.sessionId)
                        : undefined
                )
            }
        }

        // Normalize _meta to include both new (ui.resourceUri) and legacy (ui/resourceUri) formats
        // for compatibility with different MCP clients
        let normalizedMeta = tool._meta
        if (tool._meta?.ui?.resourceUri && !tool._meta[RESOURCE_URI_META_KEY]) {
            normalizedMeta = {
                ...tool._meta,
                [RESOURCE_URI_META_KEY]: tool._meta.ui.resourceUri,
            }
        }

        this.server.registerTool(
            tool.name,
            {
                title: tool.title,
                description: tool.description,
                inputSchema: tool.schema.shape,
                annotations: tool.annotations,
                ...(normalizedMeta ? { _meta: normalizedMeta } : {}),
            },
            wrappedHandler as unknown as ToolCallback<TSchema>
        )
    }

    async getContext(): Promise<Context> {
        const api = await this.api()
        return {
            api,
            cache: this.cache,
            env: this.env,
            stateManager: new StateManager(this.cache, api),
            sessionManager: this.sessionManager,
        }
    }

    async init(): Promise<void> {
        const { features, version, organizationId, projectId } = this.requestProperties
        const instructions = version === 2 ? INSTRUCTIONS_V2 : INSTRUCTIONS_V1
        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        // Pre-seed cache with org/project IDs from headers/query params
        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        if (projectId) {
            await this.cache.set('projectId', projectId)
        }

        // When project ID is provided, both switch tools are removed (project implies org).
        // When only organization ID is provided, only switch-organization is removed.
        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const context = await this.getContext()

        // Register prompts and resources
        await registerPrompts(this.server)
        await registerResources(this.server, context)
        await registerUiAppResources(this.server, context)

        // Register tools
        const allTools = await getToolsFromContext(context, { features, version, excludeTools })

        for (const tool of allTools) {
            this.registerTool(tool, async (params) => tool.handler(context, params))
        }
    }
}
