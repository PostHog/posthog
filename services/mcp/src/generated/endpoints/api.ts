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

export const endpointsRunCreateBodyClientQueryIdDefault = null
export const endpointsRunCreateBodyDebugDefault = false
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownGroupTypeIndexDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownHideOtherAggregationDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownHistogramBinCountDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownLimitDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownNormalizeUrlDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownPathCleaningDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemGroupTypeIndexDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemHistogramBinCountDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemNormalizeUrlDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemTypeDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneMax = 3

export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneDateFromDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneDateToDefault = null
export const endpointsRunCreateBodyFiltersOverrideOneExplicitDateDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneOperatorDefault = `exact`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneTypeDefault = `event`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoTypeDefault = `person`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeTypeDefault = `element`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourTypeDefault = `event_metadata`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveTypeDefault = `session`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixCohortNameDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixKeyDefault = `id`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixOperatorDefault = `in`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixTypeDefault = `cohort`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenTypeDefault = `recording`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightTypeDefault = `log_entry`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineGroupKeyNamesDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineGroupTypeIndexDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineTypeDefault = `group`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroTypeDefault = `feature`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneTypeDefault = `flag`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoTypeDefault = `hogql`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnethreeTypeDefault = `empty`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneeightLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneeightValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroLabelDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroValueDefault = null
export const endpointsRunCreateBodyFiltersOverrideOnePropertiesDefault = null
export const endpointsRunCreateBodyFiltersOverrideDefault = null
export const endpointsRunCreateBodyLimitDefault = null
export const endpointsRunCreateBodyOffsetDefault = null
export const endpointsRunCreateBodyRefreshDefault = `cache`
export const endpointsRunCreateBodyVariablesDefault = null
export const endpointsRunCreateBodyVersionDefault = null

export const EndpointsRunCreateBody = /* @__PURE__ */ zod.object({
    client_query_id: zod
        .union([zod.string(), zod.null()])
        .default(endpointsRunCreateBodyClientQueryIdDefault)
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
                                .default(endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownDefault),
                            breakdown_group_type_index: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownGroupTypeIndexDefault
                                ),
                            breakdown_hide_other_aggregation: zod
                                .union([zod.boolean(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownHideOtherAggregationDefault
                                ),
                            breakdown_histogram_bin_count: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownHistogramBinCountDefault
                                ),
                            breakdown_limit: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownLimitDefault
                                ),
                            breakdown_normalize_url: zod
                                .union([zod.boolean(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownNormalizeUrlDefault
                                ),
                            breakdown_path_cleaning: zod
                                .union([zod.boolean(), zod.null()])
                                .default(
                                    endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownPathCleaningDefault
                                ),
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
                                                group_type_index: zod
                                                    .union([zod.number(), zod.null()])
                                                    .default(
                                                        endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemGroupTypeIndexDefault
                                                    ),
                                                histogram_bin_count: zod
                                                    .union([zod.number(), zod.null()])
                                                    .default(
                                                        endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemHistogramBinCountDefault
                                                    ),
                                                normalize_url: zod
                                                    .union([zod.boolean(), zod.null()])
                                                    .default(
                                                        endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemNormalizeUrlDefault
                                                    ),
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
                                                    .default(
                                                        endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneItemTypeDefault
                                                    ),
                                            })
                                        )
                                        .max(
                                            endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsOneMax
                                        ),
                                    zod.null(),
                                ])
                                .default(endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterOneBreakdownsDefault),
                        }),
                        zod.null(),
                    ])
                    .default(endpointsRunCreateBodyFiltersOverrideOneBreakdownFilterDefault),
                date_from: zod
                    .union([zod.string(), zod.null()])
                    .default(endpointsRunCreateBodyFiltersOverrideOneDateFromDefault),
                date_to: zod
                    .union([zod.string(), zod.null()])
                    .default(endpointsRunCreateBodyFiltersOverrideOneDateToDefault),
                explicitDate: zod
                    .union([zod.boolean(), zod.null()])
                    .default(endpointsRunCreateBodyFiltersOverrideOneExplicitDateDefault),
                properties: zod
                    .union([
                        zod.array(
                            zod.union([
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwoValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemThreeValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFourValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemFiveValueDefault
                                        ),
                                }),
                                zod.object({
                                    cohort_name: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixCohortNameDefault
                                        ),
                                    key: zod
                                        .literal('id')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixKeyDefault
                                        ),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSixTypeDefault
                                        ),
                                    value: zod.number(),
                                }),
                                zod.object({
                                    key: zod.union([
                                        zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                        zod.string(),
                                    ]),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemSevenValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemEightValueDefault
                                        ),
                                }),
                                zod.object({
                                    group_key_names: zod
                                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineGroupKeyNamesDefault
                                        ),
                                    group_type_index: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineGroupTypeIndexDefault
                                        ),
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemNineValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroTypeDefault
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnezeroValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string().describe('The key should be the flag ID'),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneLabelDefault
                                        ),
                                    operator: zod
                                        .literal('flag_evaluates_to')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Feature flag dependency'),
                                    value: zod
                                        .union([zod.boolean(), zod.string()])
                                        .describe('The value can be true, false, or a variant name'),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoLabelDefault
                                        ),
                                    type: zod
                                        .literal('hogql')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnetwoValueDefault
                                        ),
                                }),
                                zod.object({
                                    type: zod
                                        .literal('empty')
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnethreeTypeDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefourValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnefiveValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesixValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnesevenValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneeightLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOneeightValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineLabelDefault
                                        ),
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
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineTypeDefault
                                        ),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                            zod.null(),
                                        ])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemOnenineValueDefault
                                        ),
                                }),
                                zod.object({
                                    key: zod.string(),
                                    label: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroLabelDefault
                                        ),
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
                                        .default(
                                            endpointsRunCreateBodyFiltersOverrideOnePropertiesOneItemTwozeroValueDefault
                                        ),
                                }),
                            ])
                        ),
                        zod.null(),
                    ])
                    .default(endpointsRunCreateBodyFiltersOverrideOnePropertiesDefault),
            }),
            zod.null(),
        ])
        .default(endpointsRunCreateBodyFiltersOverrideDefault),
    limit: zod
        .union([zod.number(), zod.null()])
        .default(endpointsRunCreateBodyLimitDefault)
        .describe('Maximum number of results to return. If not provided, returns all results.'),
    offset: zod
        .union([zod.number(), zod.null()])
        .default(endpointsRunCreateBodyOffsetDefault)
        .describe('Number of results to skip. Must be used together with limit. Only supported for HogQL endpoints.'),
    refresh: zod
        .union([zod.enum(['cache', 'force', 'direct']), zod.null()])
        .default(endpointsRunCreateBodyRefreshDefault),
    variables: zod
        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
        .default(endpointsRunCreateBodyVariablesDefault)
        .describe(
            'Variables to parameterize the endpoint query. The key is the variable name and the value is the variable value.\n\nFor HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`\n\nFor non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`\n\nFor materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.\n\nUnknown variable names will return a 400 error.'
        ),
    version: zod
        .union([zod.number(), zod.null()])
        .default(endpointsRunCreateBodyVersionDefault)
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
