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
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsMax = 3

export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneOperatorDefault = `exact`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemTwoTypeDefault = `person`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemThreeTypeDefault = `element`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemFourTypeDefault = `event_metadata`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemFiveTypeDefault = `session`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixKeyDefault = `id`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixOperatorDefault = `in`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixTypeDefault = `cohort`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSevenTypeDefault = `recording`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemEightTypeDefault = `log_entry`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemNineTypeDefault = `group`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnezeroTypeDefault = `feature`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneoneOperatorDefault = `flag_evaluates_to`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneoneTypeDefault = `flag`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnetwoTypeDefault = `hogql`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnethreeTypeDefault = `empty`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnefourTypeDefault = `data_warehouse`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnefiveTypeDefault = `data_warehouse_person_property`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnesixTypeDefault = `error_tracking_issue`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnenineTypeDefault = `revenue_analytics`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesItemTwozeroTypeDefault = `workflow_variable`
export const endpointsRunCreateBodyRefreshDefault = `cache`

export const EndpointsRunCreateBody = /* @__PURE__ */ zod.object({
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
                        .default(endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownTypeDefault),
                    breakdowns: zod
                        .array(
                            zod.object({
                                group_type_index: zod.number().nullish(),
                                histogram_bin_count: zod.number().nullish(),
                                normalize_url: zod.boolean().nullish(),
                                property: zod.union([zod.string(), zod.number()]),
                                type: zod
                                    .enum([
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
                                    ])
                                    .nullish(),
                            })
                        )
                        .max(endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsMax)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneOperatorDefault),
                            type: zod
                                .enum(['event'])
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneTypeDefault)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemTwoTypeDefault)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemThreeTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemFourTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemFiveTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixKeyDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixOperatorDefault),
                            type: zod
                                .enum(['cohort'])
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSixTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemSevenTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemEightTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemNineTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnezeroTypeDefault)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneoneOperatorDefault)
                                .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                            type: zod
                                .enum(['flag'])
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOneoneTypeDefault)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnetwoTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnethreeTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnefourTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnefiveTypeDefault),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnesixTypeDefault),
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
                            type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
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
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemOnenineTypeDefault),
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
                                .enum(['workflow_variable'])
                                .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesItemTwozeroTypeDefault),
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
    refresh: zod.enum(['cache', 'force', 'direct']).default(endpointsRunCreateBodyRefreshDefault),
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
