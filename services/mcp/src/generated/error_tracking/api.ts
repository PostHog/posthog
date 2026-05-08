/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 15 enabled ops
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

export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnenineValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault = null
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`
export const errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneValueDefault = null

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoLabelDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwoValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemThreeValueDefault),
                    }),
                    zod.object({
                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFourValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemFiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSixValueDefault),
                    }),
                    zod.object({
                        cohort_name: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault),
                        key: zod
                            .literal('id')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemSevenLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemEightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemNineValueDefault),
                    }),
                    zod.object({
                        group_key_names: zod
                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                            .default(
                                errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault
                            ),
                        group_type_index: zod
                            .union([zod.number(), zod.null()])
                            .default(
                                errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault
                            ),
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneoneValueDefault),
                    }),
                    zod.object({
                        key: zod.string().describe('The key should be the flag ID'),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault),
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault),
                    }),
                    zod.object({
                        type: zod
                            .literal('empty')
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesixValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOneeightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemOnenineValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingAssignmentRulesCreateBodyFiltersOneValuesItemTwooneValueDefault),
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

export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnenineValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault = null
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`
export const errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneValueDefault = null

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            type: zod.enum(['AND', 'OR']),
            values: zod.array(
                zod.union([
                    zod.unknown(),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoLabelDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwoValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemThreeValueDefault),
                    }),
                    zod.object({
                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFourValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemFiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSixValueDefault),
                    }),
                    zod.object({
                        cohort_name: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault),
                        key: zod
                            .literal('id')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemSevenLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemEightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemNineValueDefault),
                    }),
                    zod.object({
                        group_key_names: zod
                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                            .default(
                                errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault
                            ),
                        group_type_index: zod
                            .union([zod.number(), zod.null()])
                            .default(
                                errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault
                            ),
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneoneValueDefault),
                    }),
                    zod.object({
                        key: zod.string().describe('The key should be the flag ID'),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault),
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault),
                    }),
                    zod.object({
                        type: zod
                            .literal('empty')
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesixValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOneeightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemOnenineValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingGroupingRulesCreateBodyFiltersOneValuesItemTwooneValueDefault),
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
    first_seen: zod.iso.datetime({ offset: true }).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string(), zod.null()]).optional(),
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
                        zod.literal(null),
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
        .object({
            id: zod.union([zod.string(), zod.number()]).describe('User ID or role UUID to filter by.'),
            type: zod
                .enum(['user', 'role'])
                .describe('* `user` - user\n* `role` - role')
                .describe('Assignee target type: user or role.\n\n* `user` - user\n* `role` - role'),
        })
        .nullish()
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
                        zod.literal(null),
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

export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoOperatorDefault = `exact`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoTypeDefault = `event`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeTypeDefault = `person`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourTypeDefault = `element`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveTypeDefault = `event_metadata`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixTypeDefault = `session`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenKeyDefault = `id`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenOperatorDefault = `in`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenTypeDefault = `cohort`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightTypeDefault = `recording`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineTypeDefault = `log_entry`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroTypeDefault = `group`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneTypeDefault = `feature`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoTypeDefault = `flag`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeTypeDefault = `hogql`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault = `empty`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveTypeDefault = `data_warehouse`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnenineValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroTypeDefault = `revenue_analytics`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault = null
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneTypeDefault = `workflow_variable`
export const errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneValueDefault = null
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoLabelDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwoValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemThreeValueDefault),
                    }),
                    zod.object({
                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFourValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemFiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSixValueDefault),
                    }),
                    zod.object({
                        cohort_name: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenCohortNameDefault),
                        key: zod
                            .literal('id')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenKeyDefault),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemSevenLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemEightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemNineValueDefault),
                    }),
                    zod.object({
                        group_key_names: zod
                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                            .default(
                                errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroGroupKeyNamesDefault
                            ),
                        group_type_index: zod
                            .union([zod.number(), zod.null()])
                            .default(
                                errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroGroupTypeIndexDefault
                            ),
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnezeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneoneValueDefault),
                    }),
                    zod.object({
                        key: zod.string().describe('The key should be the flag ID'),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnetwoLabelDefault),
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
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeLabelDefault),
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnethreeValueDefault),
                    }),
                    zod.object({
                        type: zod
                            .literal('empty')
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefourTypeDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnefiveValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesixValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnesevenValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOneeightValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnenineLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemOnenineValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwozeroValueDefault),
                    }),
                    zod.object({
                        key: zod.string(),
                        label: zod
                            .union([zod.string(), zod.null()])
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneLabelDefault),
                        operator: zod.enum([
                            'exact',
                            'is_not',
                            'icontains',
                            'not_icontains',
                            'regex',
                            'not_regex',
                            'gt',
                            'gte',
                            'lt',
                            'lte',
                            'is_set',
                            'is_not_set',
                            'is_date_exact',
                            'is_date_before',
                            'is_date_after',
                            'between',
                            'not_between',
                            'min',
                            'max',
                            'in',
                            'not_in',
                            'is_cleaned_path_exact',
                            'flag_evaluates_to',
                            'semver_eq',
                            'semver_neq',
                            'semver_gt',
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
                            .default(errorTrackingSuppressionRulesCreateBodyFiltersOneValuesItemTwooneValueDefault),
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
