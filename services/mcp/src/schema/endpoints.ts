import { z } from 'zod'

// Response schemas

export const EndpointVersionSchema = z.object({
    id: z.string(),
    version: z.number(),
    query: z.any(),
    description: z.string().nullish(),
    cache_age_seconds: z.number().nullish(),
    created_at: z.string(),
    created_by: z.any().nullish(),
})

export type EndpointVersion = z.infer<typeof EndpointVersionSchema>

export const EndpointSchema = z.object({
    id: z.string(),
    name: z.string(),
    is_active: z.boolean(),
    current_version: z.number(),
    created_at: z.string(),
    updated_at: z.string(),
    created_by: z.any().nullish(),
    // current version details are inlined
    query: z.any().nullish(),
    description: z.string().nullish(),
    cache_age_seconds: z.number().nullish(),
    is_materialized: z.boolean().optional(),
    materialization_status: z.any().nullish(),
    derived_from_insight: z.string().nullish(),
})

export type Endpoint = z.infer<typeof EndpointSchema>

// Input schemas

export const ListEndpointsInputSchema = z.object({
    is_active: z.boolean().optional().describe('Filter by active status'),
    limit: z.number().int().positive().optional().describe('Maximum number of endpoints to return'),
    offset: z.number().int().min(0).optional().describe('Number of endpoints to skip for pagination'),
})

export type ListEndpointsInput = z.infer<typeof ListEndpointsInputSchema>

export const GetEndpointInputSchema = z.object({
    name: z.string().describe('The URL-safe name of the endpoint'),
    version: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Specific version number to retrieve. If omitted, returns the current version'),
})

export type GetEndpointInput = z.infer<typeof GetEndpointInputSchema>

export const CreateEndpointInputSchema = z.object({
    name: z.string().describe('URL-safe name for the endpoint (letters, numbers, hyphens, underscores)'),
    query: z
        .record(z.any())
        .describe(
            'The query object. Must include a "kind" field (e.g. "HogQLQuery" with a "query" string field, or an insight query kind)'
        ),
    description: z.string().optional().describe('Description for this endpoint version'),
    is_active: z.boolean().optional().describe('Whether this endpoint is available via the API. Defaults to true'),
    cache_age_seconds: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Cache age in seconds. If omitted, uses default interval-based caching'),
})

export type CreateEndpointInput = z.infer<typeof CreateEndpointInputSchema>

export const UpdateEndpointInputSchema = z.object({
    query: z.record(z.any()).optional().describe('Updated query object. Changing the query creates a new version'),
    description: z.string().optional().describe('Updated description'),
    is_active: z.boolean().optional().describe('Enable or disable the endpoint'),
    cache_age_seconds: z
        .number()
        .int()
        .positive()
        .nullable()
        .optional()
        .describe('Updated cache age in seconds. Set to null for default caching'),
    is_materialized: z.boolean().optional().describe('Enable or disable materialization for this endpoint'),
})

export type UpdateEndpointInput = z.infer<typeof UpdateEndpointInputSchema>

export const RunEndpointInputSchema = z.object({
    variables: z
        .record(z.any())
        .optional()
        .describe(
            'Variables to parameterize the query. For HogQL endpoints: keys must match a variable code_name (e.g. {"event_name": "$pageview"}). For non-materialized insight endpoints: use "date_from"/"date_to" to filter date range. For materialized insight endpoints: use breakdown property names as keys (e.g. {"$browser": "Chrome"}).'
        ),
    limit: z.number().int().positive().optional().describe('Maximum number of rows to return'),
    offset: z.number().int().min(0).optional().describe('Number of rows to skip for pagination'),
    refresh: z
        .enum(['cache', 'force', 'direct'])
        .optional()
        .describe(
            "Refresh mode: 'cache' (default, return cached or materialized results if available), 'force' (bypass cache, return materialized or run raw query), 'direct' (only for materialized endpoints, bypass materialized table and run against raw data)"
        ),
    version: z
        .number()
        .int()
        .positive()
        .optional()
        .describe('Specific endpoint version to execute. If omitted, uses current version'),
})

export type RunEndpointInput = z.infer<typeof RunEndpointInputSchema>

export const ListEndpointVersionsInputSchema = z.object({
    limit: z.number().int().positive().optional().describe('Maximum number of versions to return'),
    offset: z.number().int().min(0).optional().describe('Number of versions to skip for pagination'),
})

export type ListEndpointVersionsInput = z.infer<typeof ListEndpointVersionsInputSchema>
