/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ErrorTrackingAssignmentRulesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingAssignmentRulesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingAssignmentRulesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .enum(['event'])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .enum(['cohort'])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .enum(['flag'])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
            ),
        })
        .describe('Property-group filters that define when this rule matches incoming error events.'),
    assignee: zod
        .object({
            type: zod
                .enum(['user', 'role'])
                .describe('* `user` - user\n* `role` - role')
                .describe(
                    'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n* `user` - user\n* `role` - role'
                ),
            id: zod
                .union([zod.number(), zod.string()])
                .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
        })
        .describe('User or role to assign matching issues to.'),
})

export const ErrorTrackingGroupingRulesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingGroupingRulesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .enum(['event'])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .enum(['cohort'])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .enum(['flag'])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
            ),
        })
        .describe('Property-group filters that define which exceptions should be grouped into the same issue.'),
    assignee: zod
        .object({
            type: zod
                .enum(['user', 'role'])
                .describe('* `user` - user\n* `role` - role')
                .describe(
                    'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n* `user` - user\n* `role` - role'
                ),
            id: zod
                .union([zod.number(), zod.string()])
                .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
        })
        .nullish()
        .describe('Optional user or role to assign to issues created by this grouping rule.'),
    description: zod
        .string()
        .nullish()
        .describe('Optional human-readable description of what this grouping rule is for.'),
})

export const ErrorTrackingIssuesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingIssuesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string()]).nullish(),
            type: zod.string().optional(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.string().optional(),
                integration: zod
                    .object({
                        id: zod.number().optional(),
                        kind: zod.string().optional(),
                        display_name: zod.string().optional(),
                    })
                    .optional(),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.string(),
                external_url: zod.string().optional(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesMergeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesMergeCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.string()).describe('IDs of the issues to merge into the current issue.'),
})

export const ErrorTrackingIssuesSplitCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingIssuesSplitCreateBody = /* @__PURE__ */ zod.object({
    fingerprints: zod
        .array(
            zod.object({
                fingerprint: zod.string().describe('Fingerprint to split into a new issue.'),
                name: zod
                    .string()
                    .optional()
                    .describe('Optional name for the new issue created from this fingerprint.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Optional description for the new issue created from this fingerprint.'),
            })
        )
        .optional()
        .describe('Fingerprints to split into new issues. Each fingerprint becomes its own new issue.'),
})

export const ErrorTrackingSuppressionRulesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSuppressionRulesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingSuppressionRulesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`
export const errorTrackingSuppressionRulesCreateBodySamplingRateDefault = 1
export const errorTrackingSuppressionRulesCreateBodySamplingRateMin = 0
export const errorTrackingSuppressionRulesCreateBodySamplingRateMax = 1

export const ErrorTrackingSuppressionRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .enum(['event'])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .enum(['cohort'])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .enum(['flag'])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
            ),
        })
        .optional()
        .describe(
            'Optional property-group filters that define which incoming error events should be suppressed. Omit this field or provide an empty `values` array to create a match-all suppression rule.'
        ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRulesCreateBodySamplingRateMin)
        .max(errorTrackingSuppressionRulesCreateBodySamplingRateMax)
        .default(errorTrackingSuppressionRulesCreateBodySamplingRateDefault)
        .describe('Fraction of matching events to suppress. Use `1.0` to suppress all matching events.'),
})
