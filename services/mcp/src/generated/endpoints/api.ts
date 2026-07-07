/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 14 enabled ops
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
            .optional()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        data_freshness_seconds: zod
            .number()
            .nullish()
            .describe(
                'How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.'
            ),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
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
        tags: zod
            .array(zod.string())
            .nullish()
            .describe('List of tag names to associate with this endpoint. Replaces any existing tags.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Breakdown property names that may be omitted on /run. Omitted ones return data aggregated across all values of that breakdown. Defaults to [] — every breakdown variable is required.'
            ),
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
            .optional()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        data_freshness_seconds: zod
            .number()
            .nullish()
            .describe(
                'How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.'
            ),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
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
        tags: zod
            .array(zod.string())
            .nullish()
            .describe('List of tag names to associate with this endpoint. Replaces any existing tags.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Breakdown property names that may be omitted on /run. Omitted ones return data aggregated across all values of that breakdown. Defaults to [] — every breakdown variable is required.'
            ),
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

export const EndpointsLogsRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const endpointsLogsRetrieveQueryLimitDefault = 50
export const endpointsLogsRetrieveQueryLimitMax = 500

export const EndpointsLogsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod.iso.datetime({ offset: true }).optional().describe('Only return entries after this ISO 8601 timestamp.'),
    before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only return entries before this ISO 8601 timestamp.'),
    instance_id: zod.string().min(1).optional().describe('Filter logs to a specific execution instance.'),
    level: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR."
        ),
    limit: zod
        .number()
        .min(1)
        .max(endpointsLogsRetrieveQueryLimitMax)
        .default(endpointsLogsRetrieveQueryLimitDefault)
        .describe('Maximum number of log entries to return (1-500, default 50).'),
    search: zod.string().min(1).optional().describe('Case-insensitive substring search across log messages.'),
})

/**
 * Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.
 */
export const EndpointsMaterializationPreviewCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsMaterializationPreviewCreateBody = /* @__PURE__ */ zod.object({
    version: zod.number().optional(),
    bucket_overrides: zod
        .record(zod.string(), zod.string())
        .nullish()
        .describe('Per-column bucket function overrides, e.g. {"timestamp": "hour"}'),
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
 * Ask AI to rewrite the endpoint's query into a semantically equivalent form that can be materialized. Only applicable to SQL (HogQL) endpoints that currently fail the materialization checks. The suggestion is validated against the live checks before being returned; nothing is saved. Requires the organization's AI data processing approval.
 */
export const EndpointsMaterializationSuggestionCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsMaterializationSuggestionCreateBody = /* @__PURE__ */ zod
    .object({
        version: zod
            .number()
            .nullish()
            .describe('Endpoint version to suggest a fix for. Defaults to the latest version.'),
    })
    .describe('Request body for the AI materialization-fix suggestion action.')

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const EndpointsOpenapiSpecRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsOpenapiSpecRetrieveQueryParams = /* @__PURE__ */ zod.object({
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
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneMax = 3

export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneOperatorDefault = `exact`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoTypeDefault = `person`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeTypeDefault = `person_metadata`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourTypeDefault = `element`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveTypeDefault = `event_metadata`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixTypeDefault = `session`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenKeyDefault = `id`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenOperatorDefault = `in`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenTypeDefault = `cohort`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightTypeDefault = `recording`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineTypeDefault = `log_entry`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroTypeDefault = `group`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneTypeDefault = `feature`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoTypeDefault = `flag`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnethreeTypeDefault = `hogql`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourTypeDefault = `empty`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroTypeDefault = `revenue_analytics`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwooneTypeDefault = `workflow_variable`
export const endpointsRunCreateBodyRefreshDefault = `cache`

export const EndpointsRunCreateBody = /* @__PURE__ */ zod.object({
    client_query_id: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Client provided query ID. Can be used to retrieve the status or cancel the query.'),
    debug: zod
        .union([zod.boolean(), zod.null()])
        .default(endpointsRunCreateBodyDebugDefault)
        .describe('Whether to include debug information (such as the executed HogQL) in the response.'),
    filters_override: zod
        .union([
            zod.object({
                breakdown_filter: zod
                    .union([
                        zod.object({
                            breakdown: zod
                                .union([
                                    zod.string(),
                                    zod.array(zod.union([zod.string(), zod.number()])),
                                    zod.number(),
                                    zod.null(),
                                ])
                                .optional(),
                            breakdown_group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                            breakdown_hide_other_aggregation: zod.union([zod.boolean(), zod.null()]).optional(),
                            breakdown_histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
                            breakdown_limit: zod.union([zod.number(), zod.null()]).optional(),
                            breakdown_normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
                            breakdown_path_cleaning: zod.union([zod.boolean(), zod.null()]).optional(),
                            breakdown_type: zod
                                .union([
                                    zod.enum([
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
                                    ]),
                                    zod.null(),
                                ])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownTypeDefault
                                ),
                            breakdowns: zod
                                .union([
                                    zod
                                        .array(
                                            zod.object({
                                                group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                                                histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
                                                normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
                                                property: zod.union([zod.string(), zod.number()]),
                                                type: zod
                                                    .union([
                                                        zod.enum([
                                                            'person',
                                                            'event',
                                                            'event_metadata',
                                                            'group',
                                                            'session',
                                                            'hogql',
                                                            'cohort',
                                                            'revenue_analytics',
                                                            'data_warehouse',
                                                            'data_warehouse_person_property',
                                                        ]),
                                                        zod.null(),
                                                    ])
                                                    .optional(),
                                            })
                                        )
                                        .max(
                                            endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneMax
                                        ),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                date_from: zod.union([zod.string(), zod.null()]).optional(),
                date_to: zod.union([zod.string(), zod.null()]).optional(),
                explicitDate: zod.union([zod.boolean(), zod.null()]).optional(),
                filterTestAccounts: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Tri-state test-account override. Null/absent = inherit; true = force on; false = force off.'
                    ),
                interval: zod
                    .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                    .optional()
                    .describe('Time granularity forced onto every insight that supports one. Absent/null = inherit.'),
                properties: zod
                    .union([
                        zod.array(
                            zod.union([
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
                                    operator: zod
                                        .union([
                                            zod.enum([
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
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneTypeDefault
                                        )
                                        .describe('Event properties'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('person')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoTypeDefault
                                        )
                                        .describe('Person properties'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('person_metadata')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeTypeDefault
                                        )
                                        .describe(
                                            'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('element')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('event_metadata')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('session')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    cohort_name: zod.union([zod.string(), zod.null()]).optional(),
                                    key: zod
                                        .literal('id')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenKeyDefault
                                        ),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
                                    operator: zod
                                        .union([
                                            zod.enum([
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
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenTypeDefault
                                        ),
                                    value: zod.number(),
                                }),
                                zod.object({
                                    key: zod.union([
                                        zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                        zod.string(),
                                    ]),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('recording')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('log_entry')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    group_key_names: zod
                                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                                        .optional(),
                                    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('group')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('feature')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/" prepended'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string().describe('The key should be the flag ID'),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
                                    operator: zod
                                        .literal('flag_evaluates_to')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoTypeDefault
                                        )
                                        .describe('Feature flag dependency'),
                                    value: zod
                                        .union([zod.boolean(), zod.string()])
                                        .describe('The value can be true, false, or a variant name'),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod
                                        .literal('hogql')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnethreeTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    type: zod
                                        .literal('empty')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourTypeDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('data_warehouse')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('data_warehouse_person_property')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('error_tracking_issue')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                    type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('revenue_analytics')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod.union([zod.string(), zod.null()]).optional(),
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
                                        .literal('workflow_variable')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwooneTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .optional(),
                                }),
                            ])
                        ),
                        zod.null(),
                    ])
                    .optional(),
            }),
            zod.null(),
        ])
        .optional(),
    limit: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Maximum number of results to return. If not provided, returns all results.'),
    offset: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Number of results to skip. Must be used together with limit. Only supported for HogQL endpoints.'),
    refresh: zod
        .union([zod.enum(['cache', 'force', 'direct']), zod.null()])
        .default(endpointsRunCreateBodyRefreshDefault),
    variables: zod
        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
        .optional()
        .describe(
            'Variables to parameterize the endpoint query. The key is the variable name and the value is the variable value.\n\nFor HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`\n\nFor non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`\n\nFor materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.\n\nUnknown variable names will return a 400 error.'
        ),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
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

/**
 * Get the most recent execution time per endpoint (endpoint-level). Timestamps are recorded by the run path for personal-API-key calls. For per-version usage, query the query_log table directly.
 */
export const EndpointsLastExecutionTimesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EndpointsLastExecutionTimesCreateBody = /* @__PURE__ */ zod.object({
    names: zod.array(zod.string()),
})

/**
 * Get the source code of the live materialization checks, plus the rewrite contract. Lets an agent rewrite a rejected endpoint query itself: fetch these conditions, produce a semantically equivalent query that passes every check, update the endpoint with it, then confirm via materialization_status. The source is read from the running system, so it always matches the checks this instance enforces.
 */
export const EndpointsMaterializationConditionsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
