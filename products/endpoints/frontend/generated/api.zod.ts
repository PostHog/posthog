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
 * List all endpoints for the team.
 */
export const endpointsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const endpointsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const endpointsListResponseResultsItemCreatedByOneLastNameMax = 150

export const endpointsListResponseResultsItemCreatedByOneEmailMax = 254

export const EndpointsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
                name: zod.string().describe('URL-safe endpoint name, unique per team.'),
                description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
                query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
                is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
                cache_age_seconds: zod
                    .number()
                    .nullable()
                    .describe('Cache TTL in seconds, or null for default interval-based caching.'),
                endpoint_path: zod
                    .string()
                    .describe(
                        'Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).'
                    ),
                url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
                ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
                created_at: zod.iso.datetime({}).describe('When the endpoint was created (ISO 8601).'),
                updated_at: zod.iso.datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
                created_by: zod
                    .object({
                        id: zod.number(),
                        uuid: zod.uuid(),
                        distinct_id: zod
                            .string()
                            .max(endpointsListResponseResultsItemCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(endpointsListResponseResultsItemCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod.string().max(endpointsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                        email: zod.email().max(endpointsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                        role_at_organization: zod
                            .union([
                                zod
                                    .enum([
                                        'engineering',
                                        'data',
                                        'product',
                                        'founder',
                                        'leadership',
                                        'marketing',
                                        'sales',
                                        'other',
                                    ])
                                    .describe(
                                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                    ),
                                zod.enum(['']),
                                zod.literal(null),
                            ])
                            .nullish(),
                    })
                    .describe('User who created the endpoint.'),
                is_materialized: zod
                    .boolean()
                    .describe("Whether the current version's results are pre-computed to S3."),
                current_version: zod.number().describe('Latest version number.'),
                versions_count: zod.number().describe('Total number of versions for this endpoint.'),
                derived_from_insight: zod
                    .string()
                    .nullable()
                    .describe('Short ID of the source insight, if derived from one.'),
                last_executed_at: zod.iso
                    .datetime({})
                    .nullable()
                    .describe(
                        'When this endpoint was last executed via the API (ISO 8601), or null if never executed.'
                    ),
                materialization: zod
                    .object({
                        name: zod.string().describe('URL-safe endpoint name.'),
                        status: zod
                            .string()
                            .optional()
                            .describe("Current materialization status (e.g. 'Completed', 'Running')."),
                        can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
                        reason: zod
                            .string()
                            .nullish()
                            .describe(
                                'Reason why materialization is not possible (only when can_materialize is false).'
                            ),
                        last_materialized_at: zod
                            .string()
                            .nullish()
                            .describe('ISO 8601 timestamp of the last successful materialization.'),
                        error: zod.string().optional().describe('Last materialization error message, if any.'),
                        sync_frequency: zod
                            .string()
                            .nullish()
                            .describe("How often the materialization refreshes (e.g. 'every_hour')."),
                    })
                    .describe('Materialization status for an endpoint version.')
                    .describe('Materialization status and configuration for the current version.'),
                bucket_overrides: zod
                    .record(zod.string(), zod.unknown())
                    .nullable()
                    .describe('Per-column bucket overrides for range variable materialization.'),
                columns: zod
                    .array(
                        zod
                            .object({
                                name: zod.string().describe('Column name from the query SELECT clause.'),
                                type: zod
                                    .string()
                                    .describe(
                                        'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
                                    ),
                            })
                            .describe("A column in the endpoint's query result.")
                    )
                    .describe("Column names and types from the query's SELECT clause."),
            })
            .describe('Full endpoint representation returned by list/retrieve/create/update.')
    ),
})

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
 * Retrieve an endpoint, or a specific version via ?version=N.
 */
export const endpointsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const endpointsRetrieveResponseCreatedByOneFirstNameMax = 150

export const endpointsRetrieveResponseCreatedByOneLastNameMax = 150

export const endpointsRetrieveResponseCreatedByOneEmailMax = 254

export const endpointsRetrieveResponseVersionCreatedByOneDistinctIdMax = 200

export const endpointsRetrieveResponseVersionCreatedByOneFirstNameMax = 150

export const endpointsRetrieveResponseVersionCreatedByOneLastNameMax = 150

export const endpointsRetrieveResponseVersionCreatedByOneEmailMax = 254

export const EndpointsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
        name: zod.string().describe('URL-safe endpoint name, unique per team.'),
        description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
        query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
        is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
        cache_age_seconds: zod
            .number()
            .nullable()
            .describe('Cache TTL in seconds, or null for default interval-based caching.'),
        endpoint_path: zod
            .string()
            .describe(
                'Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).'
            ),
        url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
        ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
        created_at: zod.iso.datetime({}).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.iso.datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: zod
            .object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(endpointsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsRetrieveResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsRetrieveResponseCreatedByOneLastNameMax).optional(),
                email: zod.email().max(endpointsRetrieveResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        last_executed_at: zod.iso
            .datetime({})
            .nullable()
            .describe('When this endpoint was last executed via the API (ISO 8601), or null if never executed.'),
        materialization: zod
            .object({
                name: zod.string().describe('URL-safe endpoint name.'),
                status: zod
                    .string()
                    .optional()
                    .describe("Current materialization status (e.g. 'Completed', 'Running')."),
                can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
                reason: zod
                    .string()
                    .nullish()
                    .describe('Reason why materialization is not possible (only when can_materialize is false).'),
                last_materialized_at: zod
                    .string()
                    .nullish()
                    .describe('ISO 8601 timestamp of the last successful materialization.'),
                error: zod.string().optional().describe('Last materialization error message, if any.'),
                sync_frequency: zod
                    .string()
                    .nullish()
                    .describe("How often the materialization refreshes (e.g. 'every_hour')."),
            })
            .describe('Materialization status for an endpoint version.')
            .describe('Materialization status and configuration for the current version.'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Per-column bucket overrides for range variable materialization.'),
        columns: zod
            .array(
                zod
                    .object({
                        name: zod.string().describe('Column name from the query SELECT clause.'),
                        type: zod
                            .string()
                            .describe(
                                'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
                            ),
                    })
                    .describe("A column in the endpoint's query result.")
            )
            .describe("Column names and types from the query's SELECT clause."),
        version: zod.number().describe('Version number.'),
        version_id: zod.uuid().describe('Version unique identifier (UUID).'),
        endpoint_is_active: zod
            .boolean()
            .describe('Whether the parent endpoint is active (distinct from version.is_active).'),
        version_created_at: zod.string().describe('ISO 8601 timestamp when this version was created.'),
        version_updated_at: zod.string().nullable().describe('ISO 8601 timestamp when this version was last updated.'),
        version_created_by: zod
            .object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(endpointsRetrieveResponseVersionCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsRetrieveResponseVersionCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsRetrieveResponseVersionCreatedByOneLastNameMax).optional(),
                email: zod.email().max(endpointsRetrieveResponseVersionCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .nullable()
            .describe('User who created this version.'),
    })
    .describe('Extended endpoint representation when viewing a specific version.')

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

export const endpointsUpdateResponseCreatedByOneDistinctIdMax = 200

export const endpointsUpdateResponseCreatedByOneFirstNameMax = 150

export const endpointsUpdateResponseCreatedByOneLastNameMax = 150

export const endpointsUpdateResponseCreatedByOneEmailMax = 254

export const EndpointsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
        name: zod.string().describe('URL-safe endpoint name, unique per team.'),
        description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
        query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
        is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
        cache_age_seconds: zod
            .number()
            .nullable()
            .describe('Cache TTL in seconds, or null for default interval-based caching.'),
        endpoint_path: zod
            .string()
            .describe(
                'Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).'
            ),
        url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
        ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
        created_at: zod.iso.datetime({}).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.iso.datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: zod
            .object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(endpointsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.email().max(endpointsUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        last_executed_at: zod.iso
            .datetime({})
            .nullable()
            .describe('When this endpoint was last executed via the API (ISO 8601), or null if never executed.'),
        materialization: zod
            .object({
                name: zod.string().describe('URL-safe endpoint name.'),
                status: zod
                    .string()
                    .optional()
                    .describe("Current materialization status (e.g. 'Completed', 'Running')."),
                can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
                reason: zod
                    .string()
                    .nullish()
                    .describe('Reason why materialization is not possible (only when can_materialize is false).'),
                last_materialized_at: zod
                    .string()
                    .nullish()
                    .describe('ISO 8601 timestamp of the last successful materialization.'),
                error: zod.string().optional().describe('Last materialization error message, if any.'),
                sync_frequency: zod
                    .string()
                    .nullish()
                    .describe("How often the materialization refreshes (e.g. 'every_hour')."),
            })
            .describe('Materialization status for an endpoint version.')
            .describe('Materialization status and configuration for the current version.'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Per-column bucket overrides for range variable materialization.'),
        columns: zod
            .array(
                zod
                    .object({
                        name: zod.string().describe('Column name from the query SELECT clause.'),
                        type: zod
                            .string()
                            .describe(
                                'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
                            ),
                    })
                    .describe("A column in the endpoint's query result.")
            )
            .describe("Column names and types from the query's SELECT clause."),
    })
    .describe('Full endpoint representation returned by list/retrieve/create/update.')

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

export const endpointsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const endpointsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const endpointsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const endpointsPartialUpdateResponseCreatedByOneEmailMax = 254

export const EndpointsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
        name: zod.string().describe('URL-safe endpoint name, unique per team.'),
        description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
        query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
        is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
        cache_age_seconds: zod
            .number()
            .nullable()
            .describe('Cache TTL in seconds, or null for default interval-based caching.'),
        endpoint_path: zod
            .string()
            .describe(
                'Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).'
            ),
        url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
        ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
        created_at: zod.iso.datetime({}).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.iso.datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: zod
            .object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(endpointsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.email().max(endpointsPartialUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        last_executed_at: zod.iso
            .datetime({})
            .nullable()
            .describe('When this endpoint was last executed via the API (ISO 8601), or null if never executed.'),
        materialization: zod
            .object({
                name: zod.string().describe('URL-safe endpoint name.'),
                status: zod
                    .string()
                    .optional()
                    .describe("Current materialization status (e.g. 'Completed', 'Running')."),
                can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
                reason: zod
                    .string()
                    .nullish()
                    .describe('Reason why materialization is not possible (only when can_materialize is false).'),
                last_materialized_at: zod
                    .string()
                    .nullish()
                    .describe('ISO 8601 timestamp of the last successful materialization.'),
                error: zod.string().optional().describe('Last materialization error message, if any.'),
                sync_frequency: zod
                    .string()
                    .nullish()
                    .describe("How often the materialization refreshes (e.g. 'every_hour')."),
            })
            .describe('Materialization status for an endpoint version.')
            .describe('Materialization status and configuration for the current version.'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Per-column bucket overrides for range variable materialization.'),
        columns: zod
            .array(
                zod
                    .object({
                        name: zod.string().describe('Column name from the query SELECT clause.'),
                        type: zod
                            .string()
                            .describe(
                                'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
                            ),
                    })
                    .describe("A column in the endpoint's query result.")
            )
            .describe("Column names and types from the query's SELECT clause."),
    })
    .describe('Full endpoint representation returned by list/retrieve/create/update.')

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
 * Get materialization status for an endpoint. Supports ?version=N query param.
 */
export const EndpointsMaterializationStatusRetrieveResponse = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('URL-safe endpoint name.'),
        status: zod.string().optional().describe("Current materialization status (e.g. 'Completed', 'Running')."),
        can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
        reason: zod
            .string()
            .nullish()
            .describe('Reason why materialization is not possible (only when can_materialize is false).'),
        last_materialized_at: zod
            .string()
            .nullish()
            .describe('ISO 8601 timestamp of the last successful materialization.'),
        error: zod.string().optional().describe('Last materialization error message, if any.'),
        sync_frequency: zod.string().nullish().describe("How often the materialization refreshes (e.g. 'every_hour')."),
    })
    .describe('Materialization status for an endpoint version.')

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunRetrieveResponse = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('URL-safe endpoint name that was executed.'),
        results: zod
            .array(zod.unknown())
            .optional()
            .describe('Query result rows. Each row is a list of values matching the columns order.'),
        columns: zod.array(zod.string()).optional().describe('Column names from the query SELECT clause.'),
        hasMore: zod.boolean().optional().describe('Whether more results are available beyond the limit.'),
        endpoint_version: zod.number().optional().describe('Version number of the endpoint that was executed.'),
    })
    .describe('Response from executing an endpoint query.')

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const EndpointsRunCreateResponse = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('URL-safe endpoint name that was executed.'),
        results: zod
            .array(zod.unknown())
            .optional()
            .describe('Query result rows. Each row is a list of values matching the columns order.'),
        columns: zod.array(zod.string()).optional().describe('Column names from the query SELECT clause.'),
        hasMore: zod.boolean().optional().describe('Whether more results are available beyond the limit.'),
        endpoint_version: zod.number().optional().describe('Version number of the endpoint that was executed.'),
    })
    .describe('Response from executing an endpoint query.')

/**
 * List all versions for an endpoint.
 */
export const endpointsVersionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const endpointsVersionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const endpointsVersionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const endpointsVersionsListResponseResultsItemCreatedByOneEmailMax = 254

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneDistinctIdMax = 200

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneFirstNameMax = 150

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneLastNameMax = 150

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneEmailMax = 254

export const EndpointsVersionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
                name: zod.string().describe('URL-safe endpoint name, unique per team.'),
                description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
                query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
                is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
                cache_age_seconds: zod
                    .number()
                    .nullable()
                    .describe('Cache TTL in seconds, or null for default interval-based caching.'),
                endpoint_path: zod
                    .string()
                    .describe(
                        'Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).'
                    ),
                url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
                ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
                created_at: zod.iso.datetime({}).describe('When the endpoint was created (ISO 8601).'),
                updated_at: zod.iso.datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
                created_by: zod
                    .object({
                        id: zod.number(),
                        uuid: zod.uuid(),
                        distinct_id: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemCreatedByOneLastNameMax)
                            .optional(),
                        email: zod.email().max(endpointsVersionsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                        role_at_organization: zod
                            .union([
                                zod
                                    .enum([
                                        'engineering',
                                        'data',
                                        'product',
                                        'founder',
                                        'leadership',
                                        'marketing',
                                        'sales',
                                        'other',
                                    ])
                                    .describe(
                                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                    ),
                                zod.enum(['']),
                                zod.literal(null),
                            ])
                            .nullish(),
                    })
                    .describe('User who created the endpoint.'),
                is_materialized: zod
                    .boolean()
                    .describe("Whether the current version's results are pre-computed to S3."),
                current_version: zod.number().describe('Latest version number.'),
                versions_count: zod.number().describe('Total number of versions for this endpoint.'),
                derived_from_insight: zod
                    .string()
                    .nullable()
                    .describe('Short ID of the source insight, if derived from one.'),
                last_executed_at: zod.iso
                    .datetime({})
                    .nullable()
                    .describe(
                        'When this endpoint was last executed via the API (ISO 8601), or null if never executed.'
                    ),
                materialization: zod
                    .object({
                        name: zod.string().describe('URL-safe endpoint name.'),
                        status: zod
                            .string()
                            .optional()
                            .describe("Current materialization status (e.g. 'Completed', 'Running')."),
                        can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
                        reason: zod
                            .string()
                            .nullish()
                            .describe(
                                'Reason why materialization is not possible (only when can_materialize is false).'
                            ),
                        last_materialized_at: zod
                            .string()
                            .nullish()
                            .describe('ISO 8601 timestamp of the last successful materialization.'),
                        error: zod.string().optional().describe('Last materialization error message, if any.'),
                        sync_frequency: zod
                            .string()
                            .nullish()
                            .describe("How often the materialization refreshes (e.g. 'every_hour')."),
                    })
                    .describe('Materialization status for an endpoint version.')
                    .describe('Materialization status and configuration for the current version.'),
                bucket_overrides: zod
                    .record(zod.string(), zod.unknown())
                    .nullable()
                    .describe('Per-column bucket overrides for range variable materialization.'),
                columns: zod
                    .array(
                        zod
                            .object({
                                name: zod.string().describe('Column name from the query SELECT clause.'),
                                type: zod
                                    .string()
                                    .describe(
                                        'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
                                    ),
                            })
                            .describe("A column in the endpoint's query result.")
                    )
                    .describe("Column names and types from the query's SELECT clause."),
                version: zod.number().describe('Version number.'),
                version_id: zod.uuid().describe('Version unique identifier (UUID).'),
                endpoint_is_active: zod
                    .boolean()
                    .describe('Whether the parent endpoint is active (distinct from version.is_active).'),
                version_created_at: zod.string().describe('ISO 8601 timestamp when this version was created.'),
                version_updated_at: zod
                    .string()
                    .nullable()
                    .describe('ISO 8601 timestamp when this version was last updated.'),
                version_created_by: zod
                    .object({
                        id: zod.number(),
                        uuid: zod.uuid(),
                        distinct_id: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemVersionCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemVersionCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod
                            .string()
                            .max(endpointsVersionsListResponseResultsItemVersionCreatedByOneLastNameMax)
                            .optional(),
                        email: zod.email().max(endpointsVersionsListResponseResultsItemVersionCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                        role_at_organization: zod
                            .union([
                                zod
                                    .enum([
                                        'engineering',
                                        'data',
                                        'product',
                                        'founder',
                                        'leadership',
                                        'marketing',
                                        'sales',
                                        'other',
                                    ])
                                    .describe(
                                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                    ),
                                zod.enum(['']),
                                zod.literal(null),
                            ])
                            .nullish(),
                    })
                    .nullable()
                    .describe('User who created this version.'),
            })
            .describe('Extended endpoint representation when viewing a specific version.')
    ),
})

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const EndpointsLastExecutionTimesCreateBody = /* @__PURE__ */ zod.object({
    names: zod.array(zod.string()),
})

export const endpointsLastExecutionTimesCreateResponseQueryStatusCompleteDefault = false
export const endpointsLastExecutionTimesCreateResponseQueryStatusDashboardIdDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusEndTimeDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusErrorDefault = false
export const endpointsLastExecutionTimesCreateResponseQueryStatusErrorMessageDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusExpirationTimeDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusInsightIdDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusLabelsDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusPickupTimeDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusQueryAsyncDefault = true
export const endpointsLastExecutionTimesCreateResponseQueryStatusResultsDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusStartTimeDefault = null
export const endpointsLastExecutionTimesCreateResponseQueryStatusTaskIdDefault = null

export const EndpointsLastExecutionTimesCreateResponse = /* @__PURE__ */ zod.object({
    query_status: zod.object({
        complete: zod
            .boolean()
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusCompleteDefault)
            .describe(
                'Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.'
            ),
        dashboard_id: zod.number().default(endpointsLastExecutionTimesCreateResponseQueryStatusDashboardIdDefault),
        end_time: zod.iso
            .datetime({})
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusEndTimeDefault)
            .describe('When did the query execution task finish (whether successfully or not).'),
        error: zod
            .boolean()
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusErrorDefault)
            .describe(
                'If the query failed, this will be set to true. More information can be found in the error_message field.'
            ),
        error_message: zod.string().default(endpointsLastExecutionTimesCreateResponseQueryStatusErrorMessageDefault),
        expiration_time: zod.iso
            .datetime({})
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusExpirationTimeDefault),
        id: zod.string(),
        insight_id: zod.number().default(endpointsLastExecutionTimesCreateResponseQueryStatusInsightIdDefault),
        labels: zod.array(zod.string()).default(endpointsLastExecutionTimesCreateResponseQueryStatusLabelsDefault),
        pickup_time: zod.iso
            .datetime({})
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusPickupTimeDefault)
            .describe('When was the query execution task picked up by a worker.'),
        query_async: zod
            .literal(true)
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusQueryAsyncDefault)
            .describe('ONLY async queries use QueryStatus.'),
        query_progress: zod
            .object({
                active_cpu_time: zod.number(),
                bytes_read: zod.number(),
                estimated_rows_total: zod.number(),
                rows_read: zod.number(),
                time_elapsed: zod.number(),
            })
            .nullish(),
        results: zod.unknown().default(endpointsLastExecutionTimesCreateResponseQueryStatusResultsDefault),
        start_time: zod.iso
            .datetime({})
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusStartTimeDefault)
            .describe('When was query execution task enqueued.'),
        task_id: zod.string().default(endpointsLastExecutionTimesCreateResponseQueryStatusTaskIdDefault),
        team_id: zod.number(),
    }),
})
