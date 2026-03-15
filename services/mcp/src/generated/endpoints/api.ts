/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all endpoints for the team.
 */
export const EndpointsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsListQueryParams = zod.object({
    created_by: zod.number().optional(),
    is_active: zod.boolean().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const endpointsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const endpointsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const endpointsListResponseResultsItemCreatedByOneLastNameMax = 150

export const endpointsListResponseResultsItemCreatedByOneEmailMax = 254

export const EndpointsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.string().describe('Unique endpoint identifier (UUID).'),
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
                created_at: zod.string().datetime({}).describe('When the endpoint was created (ISO 8601).'),
                updated_at: zod.string().datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
                created_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
                        distinct_id: zod
                            .string()
                            .max(endpointsListResponseResultsItemCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(endpointsListResponseResultsItemCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod.string().max(endpointsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                        email: zod.string().email().max(endpointsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                    .optional()
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
                materialization: zod
                    .object({
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
export const EndpointsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsCreateBody = zod
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
    })
    .describe('Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

/**
 * Retrieve an endpoint, or a specific version via ?version=N.
 */
export const EndpointsRetrieveParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const endpointsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const endpointsRetrieveResponseCreatedByOneFirstNameMax = 150

export const endpointsRetrieveResponseCreatedByOneLastNameMax = 150

export const endpointsRetrieveResponseCreatedByOneEmailMax = 254

export const EndpointsRetrieveResponse = zod
    .object({
        id: zod.string().describe('Unique endpoint identifier (UUID).'),
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
        created_at: zod.string().datetime({}).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.string().datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(endpointsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsRetrieveResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsRetrieveResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(endpointsRetrieveResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            .optional()
            .describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        materialization: zod
            .object({
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
 * Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.
 */
export const EndpointsUpdateParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsUpdateBody = zod
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
    })
    .describe('Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

export const endpointsUpdateResponseCreatedByOneDistinctIdMax = 200

export const endpointsUpdateResponseCreatedByOneFirstNameMax = 150

export const endpointsUpdateResponseCreatedByOneLastNameMax = 150

export const endpointsUpdateResponseCreatedByOneEmailMax = 254

export const EndpointsUpdateResponse = zod
    .object({
        id: zod.string().describe('Unique endpoint identifier (UUID).'),
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
        created_at: zod.string().datetime({}).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.string().datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(endpointsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(endpointsUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(endpointsUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(endpointsUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
            .optional()
            .describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        materialization: zod
            .object({
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

export const EndpointsPartialUpdateParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Delete an endpoint and clean up materialized query.
 */
export const EndpointsDestroyParams = zod.object({
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
export const EndpointsMaterializationStatusRetrieveParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsMaterializationStatusRetrieveResponse = zod
    .object({
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
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const EndpointsOpenapiJsonRetrieveParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunRetrieveParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunCreateParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const endpointsRunCreateBodyDebugDefault = false
export const endpointsRunCreateBodyFiltersOverrideBreakdownFilterBreakdownsMax = 3

export const endpointsRunCreateBodyFiltersOverridePropertiesItemOneTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemTwoTypeDefault = `person`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemThreeTypeDefault = `element`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemFourTypeDefault = `event_metadata`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemFiveTypeDefault = `session`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemSixKeyDefault = `id`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemSixTypeDefault = `cohort`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemSevenTypeDefault = `recording`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemEightTypeDefault = `log_entry`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemNineTypeDefault = `group`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnezeroTypeDefault = `feature`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOneoneOperatorDefault = `flag_evaluates_to`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOneoneTypeDefault = `flag`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnetwoTypeDefault = `hogql`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnethreeTypeDefault = `empty`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnefourTypeDefault = `data_warehouse`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnefiveTypeDefault = `data_warehouse_person_property`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOnesixTypeDefault = `error_tracking_issue`
export const endpointsRunCreateBodyFiltersOverridePropertiesItemOneeightTypeDefault = `revenue_analytics`

export const EndpointsRunCreateBody = zod.object({
    client_query_id: zod
        .string()
        .nullish()
        .describe('Client provided query ID. Can be used to retrieve the status or cancel the query.'),
    debug: zod
        .boolean()
        .default(endpointsRunCreateBodyDebugDefault)
        .describe('Whether to include debug information (such as the executed HogQL) in the response.'),
    filters_override: zod
        .object({
            breakdown_filter: zod
                .object({
                    breakdown: zod
                        .union([zod.string(), zod.array(zod.union([zod.string(), zod.number()])), zod.number()])
                        .nullish(),
                    breakdown_group_type_index: zod.number().nullish(),
                    breakdown_hide_other_aggregation: zod.boolean().nullish(),
                    breakdown_histogram_bin_count: zod.number().nullish(),
                    breakdown_limit: zod.number().nullish(),
                    breakdown_normalize_url: zod.boolean().nullish(),
                    breakdown_path_cleaning: zod.boolean().nullish(),
                    breakdown_type: zod
                        .enum([
                            'cohort',
                            'person',
                            'event',
                            'event_metadata',
                            'group',
                            'session',
                            'hogql',
                            'data_warehouse',
                            'data_warehouse_person_property',
                            'revenue_analytics',
                        ])
                        .nullish(),
                    breakdowns: zod
                        .array(
                            zod.object({
                                group_type_index: zod.number().nullish(),
                                histogram_bin_count: zod.number().nullish(),
                                normalize_url: zod.boolean().nullish(),
                                property: zod.union([zod.string(), zod.number()]),
                                type: zod
                                    .enum([
                                        'cohort',
                                        'person',
                                        'event',
                                        'event_metadata',
                                        'group',
                                        'session',
                                        'hogql',
                                        'revenue_analytics',
                                    ])
                                    .nullish(),
                            })
                        )
                        .max(endpointsRunCreateBodyFiltersOverrideBreakdownFilterBreakdownsMax)
                        .nullish(),
                })
                .nullish(),
            date_from: zod.string().nullish(),
            date_to: zod.string().nullish(),
            explicitDate: zod.boolean().nullish(),
            properties: zod
                .array(
                    zod.union([
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod
                                .enum([
                                    'exact',
                                    'is_not',
                                    'icontains',
                                    'not_icontains',
                                    'regex',
                                    'not_regex',
                                    'gt',
                                    'gte',
                                    'lt',
                                    'lte',
                                    'is_set',
                                    'is_not_set',
                                    'is_date_exact',
                                    'is_date_before',
                                    'is_date_after',
                                    'between',
                                    'not_between',
                                    'min',
                                    'max',
                                    'in',
                                    'not_in',
                                    'is_cleaned_path_exact',
                                    'flag_evaluates_to',
                                    'semver_eq',
                                    'semver_neq',
                                    'semver_gt',
                                    'semver_gte',
                                    'semver_lt',
                                    'semver_lte',
                                    'semver_tilde',
                                    'semver_caret',
                                    'semver_wildcard',
                                    'icontains_multi',
                                    'not_icontains_multi',
                                ])
                                .nullish(),
                            type: zod
                                .enum(['event'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOneTypeDefault)
                                .describe('Event properties'),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['person'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemTwoTypeDefault)
                                .describe('Person properties'),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['element'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemThreeTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['event_metadata'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemFourTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['session'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemFiveTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            cohort_name: zod.string().nullish(),
                            key: zod
                                .enum(['id'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemSixKeyDefault),
                            label: zod.string().nullish(),
                            operator: zod
                                .enum([
                                    'exact',
                                    'is_not',
                                    'icontains',
                                    'not_icontains',
                                    'regex',
                                    'not_regex',
                                    'gt',
                                    'gte',
                                    'lt',
                                    'lte',
                                    'is_set',
                                    'is_not_set',
                                    'is_date_exact',
                                    'is_date_before',
                                    'is_date_after',
                                    'between',
                                    'not_between',
                                    'min',
                                    'max',
                                    'in',
                                    'not_in',
                                    'is_cleaned_path_exact',
                                    'flag_evaluates_to',
                                    'semver_eq',
                                    'semver_neq',
                                    'semver_gt',
                                    'semver_gte',
                                    'semver_lt',
                                    'semver_lte',
                                    'semver_tilde',
                                    'semver_caret',
                                    'semver_wildcard',
                                    'icontains_multi',
                                    'not_icontains_multi',
                                ])
                                .nullish(),
                            type: zod
                                .enum(['cohort'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemSixTypeDefault),
                            value: zod.number(),
                        }),
                        zod.object({
                            key: zod.union([
                                zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                zod.string(),
                            ]),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['recording'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemSevenTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['log_entry'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemEightTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            group_key_names: zod.record(zod.string(), zod.string()).nullish(),
                            group_type_index: zod.number().nullish(),
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['group'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemNineTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['feature'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnezeroTypeDefault)
                                .describe('Event property with "$feature/" prepended'),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string().describe('The key should be the flag ID'),
                            label: zod.string().nullish(),
                            operator: zod
                                .enum(['flag_evaluates_to'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOneoneOperatorDefault)
                                .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                            type: zod
                                .enum(['flag'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOneoneTypeDefault)
                                .describe('Feature flag dependency'),
                            value: zod
                                .union([zod.boolean(), zod.string()])
                                .describe('The value can be true, false, or a variant name'),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            type: zod
                                .enum(['hogql'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnetwoTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            type: zod
                                .enum(['empty'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnethreeTypeDefault),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['data_warehouse'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnefourTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['data_warehouse_person_property'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnefiveTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['error_tracking_issue'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOnesixTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                        zod.object({
                            key: zod.string(),
                            label: zod.string().nullish(),
                            operator: zod.enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'gte',
                                'lt',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'between',
                                'not_between',
                                'min',
                                'max',
                                'in',
                                'not_in',
                                'is_cleaned_path_exact',
                                'flag_evaluates_to',
                                'semver_eq',
                                'semver_neq',
                                'semver_gt',
                                'semver_gte',
                                'semver_lt',
                                'semver_lte',
                                'semver_tilde',
                                'semver_caret',
                                'semver_wildcard',
                                'icontains_multi',
                                'not_icontains_multi',
                            ]),
                            type: zod
                                .enum(['revenue_analytics'])
                                .default(endpointsRunCreateBodyFiltersOverridePropertiesItemOneeightTypeDefault),
                            value: zod
                                .union([
                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                    zod.string(),
                                    zod.number(),
                                    zod.boolean(),
                                ])
                                .nullish(),
                        }),
                    ])
                )
                .nullish(),
        })
        .nullish(),
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
export const EndpointsVersionsListParams = zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsVersionsListQueryParams = zod.object({
    created_by: zod.number().optional(),
    is_active: zod.boolean().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const endpointsVersionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const endpointsVersionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const endpointsVersionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const endpointsVersionsListResponseResultsItemCreatedByOneEmailMax = 254

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneDistinctIdMax = 200

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneFirstNameMax = 150

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneLastNameMax = 150

export const endpointsVersionsListResponseResultsItemVersionCreatedByOneEmailMax = 254

export const EndpointsVersionsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.string().describe('Unique endpoint identifier (UUID).'),
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
                created_at: zod.string().datetime({}).describe('When the endpoint was created (ISO 8601).'),
                updated_at: zod.string().datetime({}).describe('When the endpoint was last updated (ISO 8601).'),
                created_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
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
                        email: zod.string().email().max(endpointsVersionsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                    .optional()
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
                materialization: zod
                    .object({
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
                version_id: zod.string().describe('Version unique identifier (UUID).'),
                endpoint_is_active: zod
                    .boolean()
                    .describe('Whether the parent endpoint is active (distinct from version.is_active).'),
                version_created_at: zod.string().describe('ISO 8601 timestamp when this version was created.'),
                version_created_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
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
                        email: zod
                            .string()
                            .email()
                            .max(endpointsVersionsListResponseResultsItemVersionCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                    .nullish()
                    .describe('User who created this version.'),
            })
            .describe('Extended endpoint representation when viewing a specific version.')
    ),
})

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const EndpointsLastExecutionTimesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsLastExecutionTimesCreateBody = zod.object({
    names: zod.array(zod.string()),
})

export const endpointsLastExecutionTimesCreateResponseQueryStatusCompleteDefault = false
export const endpointsLastExecutionTimesCreateResponseQueryStatusErrorDefault = false
export const endpointsLastExecutionTimesCreateResponseQueryStatusQueryAsyncDefault = true

export const EndpointsLastExecutionTimesCreateResponse = zod.object({
    query_status: zod.object({
        complete: zod
            .boolean()
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusCompleteDefault)
            .describe(
                'Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.'
            ),
        dashboard_id: zod.number().nullish(),
        end_time: zod
            .string()
            .datetime({})
            .nullish()
            .describe('When did the query execution task finish (whether successfully or not).'),
        error: zod
            .boolean()
            .default(endpointsLastExecutionTimesCreateResponseQueryStatusErrorDefault)
            .describe(
                'If the query failed, this will be set to true. More information can be found in the error_message field.'
            ),
        error_message: zod.string().nullish(),
        expiration_time: zod.string().datetime({}).nullish(),
        id: zod.string(),
        insight_id: zod.number().nullish(),
        labels: zod.array(zod.string()).nullish(),
        pickup_time: zod
            .string()
            .datetime({})
            .nullish()
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
        results: zod.unknown().nullish(),
        start_time: zod.string().datetime({}).nullish().describe('When was query execution task enqueued.'),
        task_id: zod.string().nullish(),
        team_id: zod.number(),
    }),
})
