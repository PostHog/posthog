/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 19 enabled ops
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                        group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                        group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
        })
        .describe('Property-group filters that define which exceptions should be grouped into the same issue.'),
    assignee: zod
        .union([
            zod.object({
                type: zod
                    .enum(['user', 'role'])
                    .describe('* `user` - user\n* `role` - role')
                    .describe(
                        'Assignee type. Use `user` for a user ID or `role` for a role UUID.\n\n* `user` - user\n* `role` - role'
                    ),
                id: zod
                    .union([zod.number(), zod.string()])
                    .describe('User ID when `type` is `user`, or role UUID when `type` is `role`.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Optional user or role to assign to issues created by this grouping rule.'),
    description: zod
        .string()
        .nullish()
        .describe('Optional human-readable description of what this grouping rule is for.'),
})

export const ErrorTrackingGroupingRulesUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking grouping rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`

export const ErrorTrackingGroupingRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .union([
            zod.object({
                type: zod.enum(['AND', 'OR']),
                values: zod.array(
                    zod.union([
                        zod.unknown(),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault),
                            type: zod
                                .literal('event')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault)
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault)
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFourTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSixTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenKeyDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenOperatorDefault),
                            type: zod
                                .literal('cohort')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemNineTypeDefault),
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
                            group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                                .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                            type: zod
                                .literal('flag')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault),
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
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Property-group filters that define which exceptions should be grouped into the same issue. Omit to preserve the existing filters.'
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
        .enum(['active', 'resolved', 'suppressed'])
        .describe('* `active` - active\n* `resolved` - resolved\n* `suppressed` - suppressed')
        .optional()
        .describe(
            'Issue status to set. Deprecated archived and pending_release values are rejected.\n\n* `active` - active\n* `resolved` - resolved\n* `suppressed` - suppressed'
        ),
    name: zod.string().nullish().describe('Optional issue display name.'),
    description: zod.string().nullish().describe('Optional issue description.'),
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

/**
 * Fetch one error tracking issue with impact counts, top in_app frame, latest release, and optional sparkline.
 * @summary Get compact error tracking issue details
 */
export const ErrorTrackingQueryIssueCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingQueryIssueCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssueCreateBodyVolumeResolutionDefault = 0
export const errorTrackingQueryIssueCreateBodyVolumeResolutionMin = 0
export const errorTrackingQueryIssueCreateBodyVolumeResolutionMax = 200

export const errorTrackingQueryIssueCreateBodyIncludeSparklineDefault = false

export const ErrorTrackingQueryIssueCreateBody = /* @__PURE__ */ zod.object({
    issueId: zod.string().describe('Error tracking issue ID.'),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for issue impact and latest-event metadata. Defaults to the last 7 days.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssueCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingQueryIssueCreateBodyVolumeResolutionMin)
        .max(errorTrackingQueryIssueCreateBodyVolumeResolutionMax)
        .default(errorTrackingQueryIssueCreateBodyVolumeResolutionDefault)
        .describe('Volume buckets. Maximum 200.'),
    includeSparkline: zod
        .boolean()
        .default(errorTrackingQueryIssueCreateBodyIncludeSparklineDefault)
        .describe('Set true to include a compact numeric occurrence sparkline. Defaults to false.'),
})

/**
 * Fetch sampled exception events, stack traces, browser/SDK context, URL, and $session_id values for one issue.
 * @summary List sampled exception events for an error tracking issue
 */
export const ErrorTrackingQueryIssueEventsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingQueryIssueEventsCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssueEventsCreateBodyFilterGroupItemOperatorDefault = `exact`
export const errorTrackingQueryIssueEventsCreateBodyFilterGroupItemTypeDefault = `event`
export const errorTrackingQueryIssueEventsCreateBodySearchQueryMax = 500

export const errorTrackingQueryIssueEventsCreateBodyOrderDirectionDefault = `DESC`
export const errorTrackingQueryIssueEventsCreateBodyLimitDefault = 1
export const errorTrackingQueryIssueEventsCreateBodyLimitMax = 20

export const errorTrackingQueryIssueEventsCreateBodyOffsetDefault = 0
export const errorTrackingQueryIssueEventsCreateBodyOffsetMin = 0

export const errorTrackingQueryIssueEventsCreateBodyVerbosityDefault = `summary`
export const errorTrackingQueryIssueEventsCreateBodyOnlyAppFramesDefault = true

export const ErrorTrackingQueryIssueEventsCreateBody = /* @__PURE__ */ zod.object({
    issueId: zod.string().describe('Error tracking issue ID.'),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for sampled exception events. Defaults to the last 7 days.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssueEventsCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
                value: zod
                    .union([
                        zod.string(),
                        zod.number(),
                        zod.boolean(),
                        zod.array(zod.union([zod.string(), zod.number()])),
                    ])
                    .describe(
                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                    ),
                operator: zod
                    .union([
                        zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'gte',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_after',
                                'is_date_before',
                                'in',
                                'not_in',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .default(errorTrackingQueryIssueEventsCreateBodyFilterGroupItemOperatorDefault),
                type: zod
                    .union([
                        zod
                            .enum([
                                'event',
                                'event_metadata',
                                'feature',
                                'person',
                                'cohort',
                                'element',
                                'static-cohort',
                                'dynamic-cohort',
                                'precalculated-cohort',
                                'group',
                                'recording',
                                'log_entry',
                                'behavioral',
                                'session',
                                'hogql',
                                'data_warehouse',
                                'data_warehouse_person_property',
                                'error_tracking_issue',
                                'log',
                                'log_attribute',
                                'log_resource_attribute',
                                'span',
                                'span_attribute',
                                'span_resource_attribute',
                                'revenue_analytics',
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                            ),
                        zod.enum(['']),
                    ])
                    .default(errorTrackingQueryIssueEventsCreateBodyFilterGroupItemTypeDefault),
            })
        )
        .optional()
        .describe('Advanced flat AND property filters applied to sampled events. HogQL filters are rejected.'),
    searchQuery: zod
        .string()
        .max(errorTrackingQueryIssueEventsCreateBodySearchQueryMax)
        .optional()
        .describe('Search exception types, exception values, and current URL among sampled events.'),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .describe('* `ASC` - ASC\n* `DESC` - DESC')
        .default(errorTrackingQueryIssueEventsCreateBodyOrderDirectionDefault)
        .describe('Timestamp sort direction. Defaults to DESC.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingQueryIssueEventsCreateBodyLimitMax)
        .default(errorTrackingQueryIssueEventsCreateBodyLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingQueryIssueEventsCreateBodyOffsetMin)
        .default(errorTrackingQueryIssueEventsCreateBodyOffsetDefault)
        .describe('Pagination offset.'),
    verbosity: zod
        .enum(['summary', 'stack', 'raw'])
        .describe('* `summary` - summary\n* `stack` - stack\n* `raw` - raw')
        .default(errorTrackingQueryIssueEventsCreateBodyVerbosityDefault)
        .describe(
            'Controls exception detail size: summary, stack, or raw. Defaults to summary.\n\n* `summary` - summary\n* `stack` - stack\n* `raw` - raw'
        ),
    onlyAppFrames: zod
        .boolean()
        .default(errorTrackingQueryIssueEventsCreateBodyOnlyAppFramesDefault)
        .describe('When true, include only stack frames marked in_app. Defaults to true.'),
})

/**
 * List error tracking issues with typed filters and compact aggregate counts.
 * @summary List compact error tracking issues
 */
export const ErrorTrackingQueryIssuesListCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingQueryIssuesListCreateBodyStatusDefault = `active`
export const errorTrackingQueryIssuesListCreateBodyFilterTestAccountsDefault = true
export const errorTrackingQueryIssuesListCreateBodySearchQueryMax = 500

export const errorTrackingQueryIssuesListCreateBodyFilterGroupItemOperatorDefault = `exact`
export const errorTrackingQueryIssuesListCreateBodyFilterGroupItemTypeDefault = `event`
export const errorTrackingQueryIssuesListCreateBodyOrderByDefault = `occurrences`
export const errorTrackingQueryIssuesListCreateBodyOrderDirectionDefault = `DESC`
export const errorTrackingQueryIssuesListCreateBodyLimitDefault = 25
export const errorTrackingQueryIssuesListCreateBodyLimitMax = 100

export const errorTrackingQueryIssuesListCreateBodyOffsetDefault = 0
export const errorTrackingQueryIssuesListCreateBodyOffsetMin = 0

export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionDefault = 0
export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionMin = 0
export const errorTrackingQueryIssuesListCreateBodyVolumeResolutionMax = 200

export const errorTrackingQueryIssuesListCreateBodyReleaseMax = 500

export const errorTrackingQueryIssuesListCreateBodyUserMax = 500

export const errorTrackingQueryIssuesListCreateBodyUrlMax = 1000

export const errorTrackingQueryIssuesListCreateBodyFilePathMax = 1000

export const ErrorTrackingQueryIssuesListCreateBody = /* @__PURE__ */ zod.object({
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .optional()
                .describe('Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.'),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.'),
        })
        .optional()
        .describe('Date range for issue aggregates. Defaults to the last 7 days.'),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
        .describe(
            '* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
        )
        .default(errorTrackingQueryIssuesListCreateBodyStatusDefault)
        .describe(
            'Filter by issue status. Defaults to active.\n\n* `archived` - archived\n* `active` - active\n* `resolved` - resolved\n* `pending_release` - pending_release\n* `suppressed` - suppressed\n* `all` - all'
        ),
    assignee: zod
        .union([
            zod.object({
                id: zod.union([zod.string(), zod.number(), zod.null()]).describe('User ID or role UUID to filter by.'),
                type: zod
                    .enum(['user', 'role'])
                    .describe('* `user` - user\n* `role` - role')
                    .describe('Assignee target type: user or role.\n\n* `user` - user\n* `role` - role'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Filter by issue assignee. Omit to include all assignees.'),
    filterTestAccounts: zod
        .boolean()
        .default(errorTrackingQueryIssuesListCreateBodyFilterTestAccountsDefault)
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    searchQuery: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodySearchQueryMax)
        .optional()
        .describe('Free-text search across exception types, values, stack frames, and email fields.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe("Key of the property you're filtering on. For example `email` or `$current_url`"),
                value: zod
                    .union([
                        zod.string(),
                        zod.number(),
                        zod.boolean(),
                        zod.array(zod.union([zod.string(), zod.number()])),
                    ])
                    .describe(
                        'Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`'
                    ),
                operator: zod
                    .union([
                        zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'gte',
                                'lte',
                                'is_set',
                                'is_not_set',
                                'is_date_exact',
                                'is_date_after',
                                'is_date_before',
                                'in',
                                'not_in',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `gte` - gte\n* `lte` - lte\n* `is_set` - is_set\n* `is_not_set` - is_not_set\n* `is_date_exact` - is_date_exact\n* `is_date_after` - is_date_after\n* `is_date_before` - is_date_before\n* `in` - in\n* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .default(errorTrackingQueryIssuesListCreateBodyFilterGroupItemOperatorDefault),
                type: zod
                    .union([
                        zod
                            .enum([
                                'event',
                                'event_metadata',
                                'feature',
                                'person',
                                'cohort',
                                'element',
                                'static-cohort',
                                'dynamic-cohort',
                                'precalculated-cohort',
                                'group',
                                'recording',
                                'log_entry',
                                'behavioral',
                                'session',
                                'hogql',
                                'data_warehouse',
                                'data_warehouse_person_property',
                                'error_tracking_issue',
                                'log',
                                'log_attribute',
                                'log_resource_attribute',
                                'span',
                                'span_attribute',
                                'span_resource_attribute',
                                'revenue_analytics',
                                'flag',
                                'workflow_variable',
                            ])
                            .describe(
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
                            ),
                        zod.enum(['']),
                    ])
                    .default(errorTrackingQueryIssuesListCreateBodyFilterGroupItemTypeDefault),
            })
        )
        .optional()
        .describe(
            'Advanced flat AND property filters. Prefer typed shortcut fields when they fit. HogQL filters are rejected.'
        ),
    orderBy: zod
        .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
        .describe(
            '* `last_seen` - last_seen\n* `first_seen` - first_seen\n* `occurrences` - occurrences\n* `users` - users\n* `sessions` - sessions'
        )
        .default(errorTrackingQueryIssuesListCreateBodyOrderByDefault)
        .describe(
            'Field used to sort issues. Defaults to occurrences.\n\n* `last_seen` - last_seen\n* `first_seen` - first_seen\n* `occurrences` - occurrences\n* `users` - users\n* `sessions` - sessions'
        ),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .describe('* `ASC` - ASC\n* `DESC` - DESC')
        .default(errorTrackingQueryIssuesListCreateBodyOrderDirectionDefault)
        .describe('Sort direction. Defaults to DESC.\n\n* `ASC` - ASC\n* `DESC` - DESC'),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingQueryIssuesListCreateBodyLimitMax)
        .default(errorTrackingQueryIssuesListCreateBodyLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(errorTrackingQueryIssuesListCreateBodyOffsetMin)
        .default(errorTrackingQueryIssuesListCreateBodyOffsetDefault)
        .describe('Pagination offset.'),
    volumeResolution: zod
        .number()
        .min(errorTrackingQueryIssuesListCreateBodyVolumeResolutionMin)
        .max(errorTrackingQueryIssuesListCreateBodyVolumeResolutionMax)
        .default(errorTrackingQueryIssuesListCreateBodyVolumeResolutionDefault)
        .describe('Number of volume buckets. Defaults to 0 for compact aggregate counts.'),
    library: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by SDK/library value from event $lib, for example posthog-js.'),
    release: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyReleaseMax)
        .optional()
        .describe('Filter by exact release ID, version, or git commit ID captured in $exception_releases.'),
    fingerprint: zod
        .union([zod.string(), zod.array(zod.string()).min(1)])
        .optional()
        .describe('Filter by exact exception fingerprint hash, not fuzzy search.'),
    user: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyUserMax)
        .optional()
        .describe('Search user/email text.'),
    personId: zod.string().optional().describe('Filter by exact PostHog person UUID.'),
    url: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyUrlMax)
        .optional()
        .describe('Filter by current URL substring.'),
    filePath: zod
        .string()
        .max(errorTrackingQueryIssuesListCreateBodyFilePathMax)
        .optional()
        .describe('Search stack-frame source/file path text.'),
})

export const ErrorTrackingSettingsRetrieveSettingsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSettingsUpdateSettingsPartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingSettingsUpdateSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    project_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.'
        ),
    project_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the project-wide rate limit applies, in minutes.'),
    per_issue_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.'
        ),
    per_issue_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the per-issue rate limit applies, in minutes.'),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                        group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match (default); `0.0` drops none; `0.5` drops half. Higher values suppress more.'
        ),
})

export const ErrorTrackingSuppressionRulesUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking suppression rule.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`
export const errorTrackingSuppressionRulesUpdateBodySamplingRateMin = 0
export const errorTrackingSuppressionRulesUpdateBodySamplingRateMax = 1

export const ErrorTrackingSuppressionRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenKeyDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault),
                        value: zod.number(),
                    }),
                    zod.object({
                        key: zod.union([zod.enum(['duration', 'active_seconds', 'inactive_seconds']), zod.string()]),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemNineTypeDefault),
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
                        group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwozeroTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault),
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
        })
        .optional()
        .describe(
            'Property-group filters that define which incoming error events should be suppressed. Provide an empty `values` array to convert the rule into a match-all suppression. Omit to preserve the existing filters.'
        ),
    sampling_rate: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodySamplingRateMin)
        .max(errorTrackingSuppressionRulesUpdateBodySamplingRateMax)
        .optional()
        .describe(
            'Probability that a matching event is dropped. `1.0` drops every match; `0.0` drops none; `0.5` drops half. Higher values suppress more. Omit to preserve the existing rate.'
        ),
})

export const ErrorTrackingSymbolSetsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSymbolSetsListQueryStatusDefault = `all`

export const ErrorTrackingSymbolSetsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Sort order for symbol sets. Prefix with `-` for descending order.\n\n* `created_at` - created_at\n* `-created_at` - -created_at\n* `ref` - ref\n* `-ref` - -ref\n* `last_used` - last_used\n* `-last_used` - -last_used'
        ),
    ref: zod.string().min(1).optional().describe('Exact symbol set reference to filter by.'),
    search: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Case-insensitive substring search across reference, release version, release project, and release commit SHA.'
        ),
    status: zod
        .enum(['all', 'valid', 'invalid'])
        .default(errorTrackingSymbolSetsListQueryStatusDefault)
        .describe(
            'Upload status filter: `valid` has an uploaded file, `invalid` is missing a file, `all` returns both.\n\n* `all` - all\n* `valid` - valid\n* `invalid` - invalid'
        ),
})

export const ErrorTrackingSymbolSetsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Return a presigned URL for downloading the symbol set's source map.
 */
export const ErrorTrackingSymbolSetsDownloadRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this error tracking symbol set.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
