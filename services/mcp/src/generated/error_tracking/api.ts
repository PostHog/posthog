/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 24 enabled ops
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
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`
export const errorTrackingAssignmentRulesCreateBodyOrderKeyDefault = 0

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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .literal('event_metadata')
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .literal('data_warehouse_person_property')
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
                        type: zod
                            .literal('error_tracking_issue')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
    order_key: zod
        .number()
        .default(errorTrackingAssignmentRulesCreateBodyOrderKeyDefault)
        .describe(
            'Evaluation priority among rules; lower is evaluated first and the first matching rule wins. Defaults to 0. Pass distinct ascending values when creating several rules at once to give them a deterministic order.'
        ),
})

export const ErrorTrackingBypassRulesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingBypassRulesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ErrorTrackingBypassRulesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`

export const ErrorTrackingBypassRulesCreateBody = /* @__PURE__ */ zod.object({
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemNineTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault),
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
                            .default(errorTrackingBypassRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
        .describe(
            'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter — empty rules are rejected. To stop rate limiting entirely, adjust the rate limit settings instead of creating a match-all bypass rule.'
        ),
})

export const ErrorTrackingBypassRulesUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`

export const ErrorTrackingBypassRulesUpdateBody = /* @__PURE__ */ zod.object({
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault),
                        type: zod
                            .literal('event')
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault)
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault)
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemSixTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemNineTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault),
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
                            .default(errorTrackingBypassRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
            'Property-group filters that define which incoming error events bypass rate limiting. Must contain at least one filter. Omit to preserve the existing filters.'
        ),
})

export const ErrorTrackingExternalReferencesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod
        .number()
        .describe(
            "ID of the connected integration to create the external issue with. List the project's integrations to find the right ID and its kind (one of 'github', 'gitlab', 'linear', 'jira')."
        ),
    config: zod
        .record(zod.string(), zod.string())
        .describe(
            'Provider-specific fields describing the external issue to create. Required keys depend on the integration kind: github -> {repository, title, body}; gitlab -> {title, body}; linear -> {team_id, title, description}; jira -> {project_key, title, description}. Examples: github {"repository":"posthog","title":"Checkout TypeError","body":"Stack trace"}; linear {"team_id":"team-id","title":"Checkout TypeError","description":"Stack trace"}; jira {"project_key":"ENG","title":"Checkout TypeError","description":"Stack trace"}.'
        ),
    issue: zod.string().describe('ID of the error tracking issue to link the reference to.'),
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
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`

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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .literal('event_metadata')
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .literal('data_warehouse_person_property')
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
                        type: zod
                            .literal('error_tracking_issue')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`

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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemFourTypeDefault)
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
                                .literal('event_metadata')
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightKeyDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault),
                            type: zod
                                .literal('cohort')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemEightTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                                    errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault
                                )
                                .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                            type: zod
                                .literal('flag')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                                .literal('data_warehouse_person_property')
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
                            type: zod
                                .literal('error_tracking_issue')
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                                .default(errorTrackingGroupingRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
    id: zod.string(),
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
    id: zod.string(),
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
    id: zod.string(),
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
                                'person_metadata',
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
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `person_metadata` - person_metadata\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
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
                                'person_metadata',
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
                                '* `event` - event\n* `event_metadata` - event_metadata\n* `feature` - feature\n* `person` - person\n* `person_metadata` - person_metadata\n* `cohort` - cohort\n* `element` - element\n* `static-cohort` - static-cohort\n* `dynamic-cohort` - dynamic-cohort\n* `precalculated-cohort` - precalculated-cohort\n* `group` - group\n* `recording` - recording\n* `log_entry` - log_entry\n* `behavioral` - behavioral\n* `session` - session\n* `hogql` - hogql\n* `data_warehouse` - data_warehouse\n* `data_warehouse_person_property` - data_warehouse_person_property\n* `error_tracking_issue` - error_tracking_issue\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute\n* `span` - span\n* `span_attribute` - span_attribute\n* `span_resource_attribute` - span_resource_attribute\n* `revenue_analytics` - revenue_analytics\n* `flag` - flag\n* `workflow_variable` - workflow_variable'
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

export const ErrorTrackingRecommendationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ErrorTrackingRecommendationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
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
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .literal('event_metadata')
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .literal('data_warehouse_person_property')
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
                        type: zod
                            .literal('error_tracking_issue')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFourTypeDefault = `person_metadata`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFiveTypeDefault = `element`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSixTypeDefault = `event_metadata`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault = `session`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightKeyDefault = `id`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault = `in`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightTypeDefault = `cohort`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemNineTypeDefault = `recording`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnezeroTypeDefault = `log_entry`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault = `group`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault = `feature`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault = `flag`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault = `hogql`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault = `empty`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault = `error_tracking_issue`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwooneTypeDefault = `revenue_analytics`
export const errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault = `workflow_variable`
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemFourTypeDefault)
                            .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
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
                            .literal('event_metadata')
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemSevenTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightKeyDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightOperatorDefault),
                        type: zod
                            .literal('cohort')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemEightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneoneTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnetwoTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeOperatorDefault)
                            .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                        type: zod
                            .literal('flag')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnethreeTypeDefault)
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefourTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOnefiveTypeDefault),
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
                            .literal('data_warehouse_person_property')
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
                        type: zod
                            .literal('error_tracking_issue')
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemOneeightTypeDefault),
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
                            .default(errorTrackingSuppressionRulesUpdateBodyFiltersOneValuesItemTwotwoTypeDefault),
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
    id: zod.string(),
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
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
