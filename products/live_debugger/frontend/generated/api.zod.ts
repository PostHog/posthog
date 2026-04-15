/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsListResponseResultsItemLineNumberMin = 0
export const liveDebuggerBreakpointsListResponseResultsItemLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            repository: zod.string().nullish(),
            filename: zod.string(),
            line_number: zod
                .number()
                .min(liveDebuggerBreakpointsListResponseResultsItemLineNumberMin)
                .max(liveDebuggerBreakpointsListResponseResultsItemLineNumberMax),
            enabled: zod.boolean().optional(),
            condition: zod.string().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsCreateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsCreateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsCreateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsCreateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsCreateBodyLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * External API endpoint for client applications to fetch active breakpoints using Project API key. This endpoint allows external client applications (like Python scripts, Node.js apps, etc.) to fetch the list of active breakpoints so they can instrument their code accordingly. 

Authentication: Requires a Project API Key in the Authorization header: `Authorization: Bearer phs_<your-project-api-key>`. You can find your Project API Key in PostHog at: Settings → Project → Project API Key
 * @summary Get active breakpoints (External API)
 */
export const LiveDebuggerBreakpointsActiveRetrieveResponse = /* @__PURE__ */ zod
    .object({
        breakpoints: zod
            .array(
                zod
                    .object({
                        id: zod.uuid().describe('Unique identifier for the breakpoint'),
                        repository: zod.string().nullish().describe("Repository identifier (e.g., 'PostHog/posthog')"),
                        filename: zod.string().describe('File path where the breakpoint is set'),
                        line_number: zod.number().describe('Line number of the breakpoint'),
                        enabled: zod.boolean().describe('Whether the breakpoint is enabled'),
                        condition: zod.string().nullish().describe('Optional condition for the breakpoint'),
                    })
                    .describe('Schema for a single active breakpoint')
            )
            .describe('List of active breakpoints'),
    })
    .describe('Response schema for active breakpoints endpoint')

/**
 * Retrieve breakpoint hit events from ClickHouse with optional filtering and pagination. Returns hit events containing stack traces, local variables, and execution context from your application's runtime. 

Security: Breakpoint IDs are filtered to only include those belonging to the current team.
 * @summary Get breakpoint hits
 */
export const LiveDebuggerBreakpointsBreakpointHitsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        results: zod
            .array(
                zod
                    .object({
                        id: zod.uuid().describe('Unique identifier for the hit event'),
                        lineNumber: zod.number().describe('Line number where the breakpoint was hit'),
                        functionName: zod.string().describe('Name of the function where breakpoint was hit'),
                        timestamp: zod.iso.datetime({}).describe('When the breakpoint was hit'),
                        variables: zod
                            .record(zod.string(), zod.unknown())
                            .describe('Local variables at the time of the hit'),
                        stackTrace: zod.array(zod.unknown()).describe('Stack trace at the time of the hit'),
                        breakpoint_id: zod.uuid().describe('ID of the breakpoint that was hit'),
                        filename: zod.string().describe('Filename where the breakpoint was hit'),
                    })
                    .describe('Schema for a single breakpoint hit event')
            )
            .describe('List of breakpoint hit events'),
        count: zod.number().describe('Number of results returned'),
        has_more: zod.boolean().describe('Whether there are more results available'),
    })
    .describe('Response schema for breakpoint hits endpoint')
