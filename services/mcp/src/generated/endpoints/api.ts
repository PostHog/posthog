/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all endpoints for the team.
 */
export const EndpointsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.number().optional(),
    is_active: zod.boolean().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a new endpoint.
 */
export const EndpointsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .nullish()
            .describe(
                'Unique URL-safe name. Must start with a letter, only letters/numbers/hyphens/underscores, max 128 chars.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        cache_age_seconds: zod.number().nullish().describe('Cache TTL in seconds (60–86400).'),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
        sync_frequency: zod
            .string()
            .nullish()
            .describe("Materialization refresh frequency (e.g. 'every_hour', 'every_day')."),
        derived_from_insight: zod
            .string()
            .nullish()
            .describe('Short ID of the insight this endpoint was derived from.'),
        version: zod
            .number()
            .nullish()
            .describe('Target a specific version for updates (defaults to current version).'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.'
            ),
        deleted: zod.boolean().nullish().describe('Set to true to soft-delete this endpoint.'),
    })
    .describe('Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

/**
 * Retrieve an endpoint, or a specific version via ?version=N.
 */
export const EndpointsRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Update an existing endpoint.
 */
export const EndpointsPartialUpdateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .nullish()
            .describe(
                'Unique URL-safe name. Must start with a letter, only letters/numbers/hyphens/underscores, max 128 chars.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        cache_age_seconds: zod.number().nullish().describe('Cache TTL in seconds (60–86400).'),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
        sync_frequency: zod
            .string()
            .nullish()
            .describe("Materialization refresh frequency (e.g. 'every_hour', 'every_day')."),
        derived_from_insight: zod
            .string()
            .nullish()
            .describe('Short ID of the insight this endpoint was derived from.'),
        version: zod
            .number()
            .nullish()
            .describe('Target a specific version for updates (defaults to current version).'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.'
            ),
        deleted: zod.boolean().nullish().describe('Set to true to soft-delete this endpoint.'),
    })
    .describe('Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

/**
 * Delete an endpoint and clean up materialized query.
 */
export const EndpointsDestroyParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get materialization status for an endpoint. Supports ?version=N query param.
 */
export const EndpointsMaterializationStatusRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const EndpointsOpenapiJsonRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsOpenapiJsonRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod
        .number()
        .optional()
        .describe('Specific endpoint version to generate the spec for. Defaults to latest.'),
})

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const endpointsRunCreateBodyDebugDefault = false

export const EndpointsRunCreateBody = /* @__PURE__ */ zod.object({
    client_query_id: zod
        .string()
        .nullish()
        .describe('Client provided query ID. Can be used to retrieve the status or cancel the query.'),
    debug: zod
        .boolean()
        .default(endpointsRunCreateBodyDebugDefault)
        .describe('Whether to include debug information (such as the executed HogQL) in the response.'),
    limit: zod
        .number()
        .nullish()
        .describe('Maximum number of results to return. If not provided, returns all results.'),
    offset: zod
        .number()
        .nullish()
        .describe('Number of results to skip. Must be used together with limit. Only supported for HogQL endpoints.'),
    refresh: zod.enum(['cache', 'force', 'direct']).nullish(),
    variables: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe(
            'Variables to parameterize the endpoint query. The key is the variable name and the value is the variable value.\n\nFor HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`\n\nFor non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`\n\nFor materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.\n\nUnknown variable names will return a 400 error.'
        ),
    version: zod
        .number()
        .nullish()
        .describe('Specific endpoint version to execute. If not provided, the latest version is used.'),
})

/**
 * List all versions for an endpoint.
 */
export const EndpointsVersionsListParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsVersionsListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.number().optional(),
    is_active: zod.boolean().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})
