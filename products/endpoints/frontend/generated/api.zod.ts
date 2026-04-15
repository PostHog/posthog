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
 * Create a new endpoint.
 */
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
 * Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.
 */
export const EndpointsUpdateBody = /* @__PURE__ */ zod
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
 * Update an existing endpoint.
 */
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
 * Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.
 */
export const EndpointsMaterializationPreviewCreateBody = /* @__PURE__ */ zod.object({
    version: zod.number().optional(),
    bucket_overrides: zod
        .record(zod.string(), zod.string())
        .nullish()
        .describe('Per-column bucket function overrides, e.g. {\"timestamp\": \"hour\"}'),
})

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const EndpointsLastExecutionTimesCreateBody = /* @__PURE__ */ zod.object({
    names: zod.array(zod.string()),
})
