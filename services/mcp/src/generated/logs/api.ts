/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 16 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LogsAlertsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsAlertsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const LogsAlertsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsAlertsCreateBodyNameMax = 255

export const logsAlertsCreateBodyEnabledDefault = true
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault = `element`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault = `event_metadata`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault = `session`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault = `id`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault = `in`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault = `cohort`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault = `recording`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault = `log_entry`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `group`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `feature`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `flag`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `hogql`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `empty`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `data_warehouse`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `revenue_analytics`
export const logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault = `workflow_variable`
export const logsAlertsCreateBodyThresholdCountDefault = 100
export const logsAlertsCreateBodyThresholdCountMin = 0

export const logsAlertsCreateBodyThresholdOperatorDefault = `above`
export const logsAlertsCreateBodyWindowMinutesDefault = 5
export const logsAlertsCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsCreateBodyCooldownMinutesDefault = 0
export const logsAlertsCreateBodyCooldownMinutesMin = 0

export const LogsAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsAlertsCreateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(logsAlertsCreateBodyEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: zod
        .object({
            filterGroup: zod
                .union([
                    zod.object({
                        type: zod.enum(['AND', 'OR']),
                        values: zod.array(
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
                                                .default(
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
                                                .default(
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault
                                                ),
                                            type: zod
                                                .literal('cohort')
                                                .default(
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault
                                                )
                                                .describe(
                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                ),
                                            type: zod
                                                .literal('flag')
                                                .default(
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                    logsAlertsCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault
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
                            })
                        ),
                    }),
                    zod.null(),
                ])
                .optional(),
            serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
            severityLevels: zod
                .union([zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])), zod.null()])
                .optional(),
        })
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
        ),
    threshold_count: zod
        .number()
        .min(logsAlertsCreateBodyThresholdCountMin)
        .default(logsAlertsCreateBodyThresholdCountDefault)
        .describe(
            "Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log."
        ),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsCreateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .default(logsAlertsCreateBodyWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsCreateBodyEvaluationPeriodsMax)
        .default(logsAlertsCreateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsCreateBodyDatapointsToAlarmMax)
        .default(logsAlertsCreateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsCreateBodyCooldownMinutesMin)
        .default(logsAlertsCreateBodyCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const LogsAlertsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsAlertsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsAlertsPartialUpdateBodyNameMax = 255

export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault = `element`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault = `event_metadata`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault = `session`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault = `id`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault = `in`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault = `cohort`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault = `recording`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault = `log_entry`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `group`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `feature`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `flag`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `hogql`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `empty`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `data_warehouse`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `revenue_analytics`
export const logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault = `workflow_variable`
export const logsAlertsPartialUpdateBodyThresholdCountMin = 0

export const logsAlertsPartialUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsPartialUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsPartialUpdateBodyCooldownMinutesMin = 0

export const LogsAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: zod
        .object({
            filterGroup: zod
                .union([
                    zod.object({
                        type: zod.enum(['AND', 'OR']),
                        values: zod.array(
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
                                                .default(
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
                                                .default(
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault
                                                ),
                                            type: zod
                                                .literal('cohort')
                                                .default(
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault
                                                )
                                                .describe(
                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                ),
                                            type: zod
                                                .literal('flag')
                                                .default(
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                    logsAlertsPartialUpdateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault
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
                            })
                        ),
                    }),
                    zod.null(),
                ])
                .optional(),
            serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
            severityLevels: zod
                .union([zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])), zod.null()])
                .optional(),
        })
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
        ),
    threshold_count: zod
        .number()
        .min(logsAlertsPartialUpdateBodyThresholdCountMin)
        .optional()
        .describe(
            "Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log."
        ),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .optional()
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .optional()
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyEvaluationPeriodsMax)
        .optional()
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyDatapointsToAlarmMax)
        .optional()
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateBodyCooldownMinutesMin)
        .optional()
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const LogsAlertsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind (firing, resolved, ...) atomically.
 */
export const LogsAlertsDestinationsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams'])
        .describe('* `slack` - slack\n* `webhook` - webhook\n* `teams` - teams')
        .describe(
            'Destination type — slack, webhook, or teams.\n\n* `slack` - slack\n* `webhook` - webhook\n* `teams` - teams'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod
        .url()
        .optional()
        .describe('HTTPS endpoint to POST to. Required when type=webhook, or the Teams webhook URL when type=teams.'),
})

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const LogsAlertsDestinationsDeleteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.string())
        .min(1)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})

/**
 * Paginated event history for this alert, newest first. Returns state transitions, errored checks, and user-initiated control-plane rows (reset, enable/disable, snooze/unsnooze, threshold change) — quiet no-op check rows (where state didn't change and there was no error) are filtered out since only the last 10 are kept and they carry no forensic value. Optional `?kind=...` narrows to a single kind.
 */
export const LogsAlertsEventsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this logs alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsAlertsEventsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Simulate a logs alert on historical data using the full state machine. Read-only — no alert check records are created.
 */
export const LogsAlertsSimulateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault = `element`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault = `event_metadata`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault = `session`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault = `id`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault = `in`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault = `cohort`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault = `recording`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault = `log_entry`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `group`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `feature`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault = `flag_evaluates_to`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `flag`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `hogql`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `empty`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `data_warehouse`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse_person_property`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `error_tracking_issue`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `revenue_analytics`
export const logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault = `workflow_variable`
export const logsAlertsSimulateCreateBodyThresholdCountMin = 0

export const logsAlertsSimulateCreateBodyCheckIntervalMinutesDefault = 5
export const logsAlertsSimulateCreateBodyCheckIntervalMinutesMax = 60

export const logsAlertsSimulateCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsSimulateCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsSimulateCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsSimulateCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsSimulateCreateBodyCooldownMinutesDefault = 0
export const logsAlertsSimulateCreateBodyCooldownMinutesMin = 0

export const LogsAlertsSimulateCreateBody = /* @__PURE__ */ zod.object({
    filters: zod
        .object({
            filterGroup: zod
                .union([
                    zod.object({
                        type: zod.enum(['AND', 'OR']),
                        values: zod.array(
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
                                                .default(
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
                                                .default(
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenKeyDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenOperatorDefault
                                                ),
                                            type: zod
                                                .literal('cohort')
                                                .default(
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoOperatorDefault
                                                )
                                                .describe(
                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                ),
                                            type: zod
                                                .literal('flag')
                                                .default(
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                    logsAlertsSimulateCreateBodyFiltersOneFilterGroupOneValuesItemValuesItemTwooneTypeDefault
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
                            })
                        ),
                    }),
                    zod.null(),
                ])
                .optional(),
            serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
            severityLevels: zod
                .union([zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])), zod.null()])
                .optional(),
        })
        .describe('Filter criteria — same format as LogsAlertConfiguration.filters.'),
    threshold_count: zod
        .number()
        .min(logsAlertsSimulateCreateBodyThresholdCountMin)
        .describe('Threshold count to evaluate against.'),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod.number().describe('Window size in minutes — determines bucket interval.'),
    check_interval_minutes: zod
        .number()
        .min(1)
        .max(logsAlertsSimulateCreateBodyCheckIntervalMinutesMax)
        .default(logsAlertsSimulateCreateBodyCheckIntervalMinutesDefault)
        .describe('How often the alert is evaluated, in minutes.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsSimulateCreateBodyEvaluationPeriodsMax)
        .default(logsAlertsSimulateCreateBodyEvaluationPeriodsDefault)
        .describe('Total check periods in the N-of-M evaluation window (M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsSimulateCreateBodyDatapointsToAlarmMax)
        .default(logsAlertsSimulateCreateBodyDatapointsToAlarmDefault)
        .describe('How many periods must breach to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsSimulateCreateBodyCooldownMinutesMin)
        .default(logsAlertsSimulateCreateBodyCooldownMinutesDefault)
        .describe('Minutes to wait after firing before sending another notification.'),
    date_from: zod.string().describe("Relative date string for how far back to simulate (e.g. '-24h', '-7d', '-30d')."),
})

export const LogsAttributesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsAttributesRetrieveQueryFilterGroupDefault = []
export const logsAttributesRetrieveQueryLimitMax = 100

export const logsAttributesRetrieveQueryOffsetMin = 0

export const logsAttributesRetrieveQuerySearchValuesDefault = false
export const logsAttributesRetrieveQueryServiceNamesDefault = []

export const LogsAttributesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribute_type: zod
        .enum(['log', 'resource'])
        .optional()
        .describe(
            'Type of attributes: "log" for log attributes, "resource" for resource attributes. Defaults to "log".\n\n* `log` - log\n* `resource` - resource'
        ),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .nullish()
                .describe(
                    'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                ),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
        })
        .optional()
        .describe('Date range to search within. Defaults to last hour.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe(
                        'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                    ),
                type: zod
                    .enum(['log', 'log_attribute', 'log_resource_attribute'])
                    .describe(
                        '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                    )
                    .describe(
                        '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                    ),
                operator: zod
                    .enum([
                        'exact',
                        'is_not',
                        'icontains',
                        'not_icontains',
                        'regex',
                        'not_regex',
                        'gt',
                        'lt',
                        'is_date_exact',
                        'is_date_before',
                        'is_date_after',
                        'is_set',
                        'is_not_set',
                    ])
                    .describe(
                        '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                    )
                    .describe(
                        'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                    ),
                value: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                    ),
            })
        )
        .default(logsAttributesRetrieveQueryFilterGroupDefault)
        .describe('Property filters to narrow which logs are scanned for attributes.'),
    limit: zod
        .number()
        .min(1)
        .max(logsAttributesRetrieveQueryLimitMax)
        .optional()
        .describe('Max results (default: 100)'),
    offset: zod
        .number()
        .min(logsAttributesRetrieveQueryOffsetMin)
        .optional()
        .describe('Pagination offset (default: 0)'),
    search: zod.string().min(1).optional().describe('Search filter for attribute names'),
    search_values: zod
        .boolean()
        .default(logsAttributesRetrieveQuerySearchValuesDefault)
        .describe(
            'When true, the search query also matches attribute values (not just keys). Each result indicates whether it matched on key or value.'
        ),
    serviceNames: zod
        .array(zod.string())
        .default(logsAttributesRetrieveQueryServiceNamesDefault)
        .describe('Filter attributes to those appearing in logs from these services.'),
})

export const LogsCountCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsCountCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe('Date range for the count. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters for the query.'),
        })
        .describe('The count query to execute.'),
})

export const LogsCountRangesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsCountRangesCreateBodyQueryOneTargetBucketsDefault = 10
export const logsCountRangesCreateBodyQueryOneTargetBucketsMax = 100

export const LogsCountRangesCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe(
                    "Window to bucket. Defaults to last hour. Use a bucket's date_from/date_to from a prior response to recursively narrow into a sub-range."
                ),
            targetBuckets: zod
                .number()
                .min(1)
                .max(logsCountRangesCreateBodyQueryOneTargetBucketsMax)
                .default(logsCountRangesCreateBodyQueryOneTargetBucketsDefault)
                .describe(
                    'Approximate number of buckets to return. The bucket interval is picked adaptively from a fixed list (1/5/10s, 1/2/5/10/15/30/60/120/240/360/720/1440m) to land near this target. Defaults to 10, capped at 100.'
                ),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels. Applied before bucketing.'),
            serviceNames: zod
                .array(zod.string())
                .optional()
                .describe('Filter by service names. Applied before bucketing.'),
            searchTerm: zod
                .string()
                .optional()
                .describe('Full-text search across log bodies. Applied before bucketing.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters applied before bucketing. Same shape as `query-logs`.'),
        })
        .describe('The bucketed-count query to execute.'),
})

export const LogsQueryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsQueryCreateBodyQueryOneSeverityLevelsDefault = []
export const logsQueryCreateBodyQueryOneServiceNamesDefault = []
export const logsQueryCreateBodyQueryOneFilterGroupDefault = []
export const logsQueryCreateBodyQueryOneLimitDefault = 100
export const logsQueryCreateBodyQueryOneExcludeAttributesDefault = false

export const LogsQueryCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .default(logsQueryCreateBodyQueryOneSeverityLevelsDefault)
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .default(logsQueryCreateBodyQueryOneServiceNamesDefault)
                .describe('Filter by service names.'),
            orderBy: zod
                .enum(['latest', 'earliest'])
                .describe('* `latest` - latest\n* `earliest` - earliest')
                .optional()
                .describe('Order results by timestamp.\n\n* `latest` - latest\n* `earliest` - earliest'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(logsQueryCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            limit: zod.number().default(logsQueryCreateBodyQueryOneLimitDefault).describe('Max results (1-1000).'),
            after: zod.string().optional().describe('Pagination cursor from previous response.'),
            excludeAttributes: zod
                .boolean()
                .default(logsQueryCreateBodyQueryOneExcludeAttributesDefault)
                .describe(
                    'Omit the per-log attributes and resource_attributes maps from results to keep payloads compact. Defaults to false.'
                ),
        })
        .describe('The logs query to execute.'),
})

export const LogsServicesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LogsServicesCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe('Date range for the services aggregation. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .optional()
                .describe('Restrict the aggregation to these service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters for the query.'),
        })
        .describe('The services aggregation query to execute.'),
})

export const LogsSparklineCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsSparklineCreateBodyQueryOneSeverityLevelsDefault = []
export const logsSparklineCreateBodyQueryOneServiceNamesDefault = []
export const logsSparklineCreateBodyQueryOneFilterGroupDefault = []

export const LogsSparklineCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
                })
                .optional()
                .describe('Date range for the sparkline. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .default(logsSparklineCreateBodyQueryOneSeverityLevelsDefault)
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .default(logsSparklineCreateBodyQueryOneServiceNamesDefault)
                .describe('Filter by service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
                                'regex',
                                'not_regex',
                                'gt',
                                'lt',
                                'is_date_exact',
                                'is_date_before',
                                'is_date_after',
                                'is_set',
                                'is_not_set',
                            ])
                            .describe(
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(logsSparklineCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            sparklineBreakdownBy: zod
                .enum(['severity', 'service'])
                .describe('* `severity` - severity\n* `service` - service')
                .optional()
                .describe(
                    'Break down sparkline by "severity" (default) or "service".\n\n* `severity` - severity\n* `service` - service'
                ),
        })
        .describe('The sparkline query to execute.'),
})

export const LogsValuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const logsValuesRetrieveQueryFilterGroupDefault = []
export const logsValuesRetrieveQueryServiceNamesDefault = []

export const LogsValuesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribute_type: zod
        .enum(['log', 'resource'])
        .optional()
        .describe(
            'Type of attribute: "log" or "resource". Defaults to "log".\n\n* `log` - log\n* `resource` - resource'
        ),
    dateRange: zod
        .object({
            date_from: zod
                .string()
                .nullish()
                .describe(
                    'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                ),
            date_to: zod
                .string()
                .nullish()
                .describe('End of the date range. Same format as date_from. Omit or null for "now".'),
        })
        .optional()
        .describe('Date range to search within. Defaults to last hour.'),
    filterGroup: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe(
                        'Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").'
                    ),
                type: zod
                    .enum(['log', 'log_attribute', 'log_resource_attribute'])
                    .describe(
                        '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                    )
                    .describe(
                        '"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                    ),
                operator: zod
                    .enum([
                        'exact',
                        'is_not',
                        'icontains',
                        'not_icontains',
                        'regex',
                        'not_regex',
                        'gt',
                        'lt',
                        'is_date_exact',
                        'is_date_before',
                        'is_date_after',
                        'is_set',
                        'is_not_set',
                    ])
                    .describe(
                        '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                    )
                    .describe(
                        'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                    ),
                value: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                    ),
            })
        )
        .default(logsValuesRetrieveQueryFilterGroupDefault)
        .describe('Property filters to narrow which logs are scanned for values.'),
    key: zod.string().min(1).describe('The attribute key to get values for'),
    serviceNames: zod
        .array(zod.string())
        .default(logsValuesRetrieveQueryServiceNamesDefault)
        .describe('Filter values to those appearing in logs from these services.'),
    value: zod.string().min(1).optional().describe('Search filter for attribute values'),
})
