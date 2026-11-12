/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the alerts of the project that the caller can read.
 * @summary List alerts
 */
export const PlatformAlertsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const platformAlertsListQueryLimitMax = 1000

export const PlatformAlertsListQueryParams = () => zod.object({
    created_by: zod.string().optional().describe('Only alerts created by the user with this UUID.'),
    legacy_configuration_id: zod
        .string()
        .optional()
        .describe("Only the alert copied from, or created with, this source configuration, such as a logs alert's id."),
    limit: zod
        .number()
        .max(platformAlertsListQueryLimitMax)
        .optional()
        .describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    source_kind: zod
        .enum(['logs', 'insight', 'warehouse_source', 'warehouse_destination', 'metrics', 'traces'])
        .optional()
        .describe(
            'Only alerts of this source kind, such as metrics. A kind the caller cannot read returns no alerts.\n\n\* `logs` - Logs\n\* `insight` - Insight\n\* `warehouse_source` - Warehouse source\n\* `warehouse_destination` - Warehouse destination\n\* `metrics` - Metrics\n\* `traces` - Traces'
        ),
})

/**
 * Create an alert on the platform. The request body depends on source_kind, which picks the source product and the shape of source_config. The alert notifies nobody until a destination is added.
 * @summary Create an alert
 */
export const PlatformAlertsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const platformAlertsCreateBodyOneNameDefault = `Untitled alert`
export const platformAlertsCreateBodyOneNameMax = 255

export const platformAlertsCreateBodyOneEnabledDefault = true
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsCreateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyOneEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyOneDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyOneCooldownMinutesDefault = 0
export const platformAlertsCreateBodyOneCooldownMinutesMin = 0
export const platformAlertsCreateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyTwoNameDefault = `Untitled alert`
export const platformAlertsCreateBodyTwoNameMax = 255

export const platformAlertsCreateBodyTwoEnabledDefault = true
export const platformAlertsCreateBodyTwoSourceConfigOneQueryMax = 10000

export const platformAlertsCreateBodyTwoSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyTwoEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyTwoEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyTwoDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyTwoDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyTwoCooldownMinutesDefault = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMin = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyThreeNameDefault = `Untitled alert`
export const platformAlertsCreateBodyThreeNameMax = 255

export const platformAlertsCreateBodyThreeEnabledDefault = true
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsCreateBodyThreeSourceConfigOneConditionThresholdMin = 0

export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyThreeEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyThreeEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyThreeDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyThreeDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyThreeCooldownMinutesDefault = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMin = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFourNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFourNameMax = 255

export const platformAlertsCreateBodyFourEnabledDefault = true
export const platformAlertsCreateBodyFourSourceConfigOneDestinationIdsMax = 100

export const platformAlertsCreateBodyFourSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFourEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFourEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyFourDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFourDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyFourCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFourCooldownMinutesMin = 0
export const platformAlertsCreateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFiveNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFiveNameMax = 255

export const platformAlertsCreateBodyFiveEnabledDefault = true
export const platformAlertsCreateBodyFiveSourceConfigOneSourceIdsMax = 100

export const platformAlertsCreateBodyFiveSourceConfigOneGroupByDefault = `source`
export const platformAlertsCreateBodyFiveSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFiveEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFiveEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyFiveDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFiveDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyFiveCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMin = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMax = 2147483647

export const PlatformAlertsCreateBody = () => zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['logs'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyOneNameMax)
                .default(platformAlertsCreateBodyOneNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyOneEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
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
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
                                                                )
                                                                .describe('Person properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
                                                                )
                                                                .describe(
                                                                    'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            cohort_deleted: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort is deleted or does not exist.'
                                                                ),
                                                            cohort_missing: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort does not exist, so it cannot be restored.'
                                                                ),
                                                            cohort_name: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .literal('id')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
                                                                ),
                                                            value: zod.number(),
                                                        }),
                                                        zod.object({
                                                            key: zod.union([
                                                                zod.enum([
                                                                    'duration',
                                                                    'active_seconds',
                                                                    'inactive_seconds',
                                                                ]),
                                                                zod.string(),
                                                            ]),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            group_key_names: zod
                                                                .union([
                                                                    zod.record(zod.string(), zod.string()),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            group_type_index: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional(),
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
                                                                )
                                                                .describe(
                                                                    'Event property with \"$feature\/\" prepended'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
                                                                )
                                                                .describe('Feature flag dependency'),
                                                            value: zod
                                                                .union([zod.boolean(), zod.string()])
                                                                .describe(
                                                                    'The value can be true, false, or a variant name'
                                                                ),
                                                        }),
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            type: zod
                                                                .literal('hogql')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'log',
                                                                'log_attribute',
                                                                'log_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('metric_attribute')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'span',
                                                                'span_attribute',
                                                                'span_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('account_custom_property')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
                                                                )
                                                                .describe(
                                                                    'Customer analytics account custom property — the key is the property definition id'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            event_filters: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod
                                                                                    .union([
                                                                                        zod.enum([
                                                                                            'exact',
                                                                                            'is_not',
                                                                                            'icontains',
                                                                                            'not_icontains',
                                                                                            'starts_with',
                                                                                            'not_starts_with',
                                                                                            'ends_with',
                                                                                            'not_ends_with',
                                                                                            'regex',
                                                                                            'not_regex',
                                                                                            'gt',
                                                                                            'gte',
                                                                                            'lt',
                                                                                            'lte',
                                                                                            'is_set',
                                                                                            'is_not_set',
                                                                                            'is_date_exact',
                                                                                            'is_date_before',
                                                                                            'is_date_after',
                                                                                            'between',
                                                                                            'not_between',
                                                                                            'min',
                                                                                            'max',
                                                                                            'in',
                                                                                            'not_in',
                                                                                            'is_cleaned_path_exact',
                                                                                            'is_cleaned_path_not_exact',
                                                                                            'flag_evaluates_to',
                                                                                            'semver_eq',
                                                                                            'semver_neq',
                                                                                            'semver_gt',
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
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
                                                                                    )
                                                                                    .describe('Event properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
                                                                                    )
                                                                                    .describe('Person properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.enum([
                                                                                    'tag_name',
                                                                                    'text',
                                                                                    'href',
                                                                                    'selector',
                                                                                ]),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
                                                                                    )
                                                                                    .describe(
                                                                                        'Event property with \"$feature\/\" prepended'
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                type: zod
                                                                                    .literal('hogql')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
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
                                                                .optional()
                                                                .describe(
                                                                    'Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral\/cohort filters and groups'
                                                                ),
                                                            event_type: zod.enum(['events', 'actions']),
                                                            explicit_datetime: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Absolute or relative (e.g. -30d) lower date bound — alternative to time_value\/time_interval'
                                                                ),
                                                            explicit_datetime_to: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .string()
                                                                .describe(
                                                                    "Event name, or action id when event_type is 'actions'"
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            negation: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators'
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                .optional()
                                                                .describe(
                                                                    'Count comparison for performed_event_multiple, defaults to exact'
                                                                ),
                                                            operator_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Count threshold for performed_event_multiple'
                                                                ),
                                                            time_interval: zod
                                                                .union([
                                                                    zod.enum(['day', 'week', 'month', 'year']),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            time_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Relative time window size, paired with time_interval'
                                                                ),
                                                            type: zod
                                                                .literal('behavioral')
                                                                .default(
                                                                    platformAlertsCreateBodyOneSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
                                                                )
                                                                .describe(
                                                                    "Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP"
                                                                ),
                                                            value: zod.enum([
                                                                'performed_event',
                                                                'performed_event_multiple',
                                                            ]),
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
                                .union([
                                    zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])),
                                    zod.null(),
                                ])
                                .optional(),
                        })
                        .describe(
                            'The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one.'
                        ),
                    condition: zod
                        .object({
                            threshold_count: zod
                                .number()
                                .min(platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMax)
                                .describe(
                                    'Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires when the count is above or below the threshold.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes over which logs are counted.'),
                        })
                        .describe('The bound the count is checked against.'),
                })
                .describe('Settings for a logs alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsCreateBodyOneGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyOneGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyOneGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances. Defaults to mode single.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyOneEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyOneEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyOneDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyOneDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyOneCooldownMinutesMin)
                .max(platformAlertsCreateBodyOneCooldownMinutesMax)
                .default(platformAlertsCreateBodyOneCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['metrics'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyTwoNameMax)
                .default(platformAlertsCreateBodyTwoNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyTwoEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsCreateBodyTwoSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsCreateBodyTwoSourceConfigOneConditionKindDefault)
                                .describe(
                                    "threshold compares each series' latest value with `threshold`. present fires for every series the query returns, for a query that already filters to the series in breach."
                                ),
                            operator: zod
                                .union([zod.enum(['gt', 'gte', 'lt', 'lte', 'eq', 'ne']), zod.null()])
                                .optional()
                                .describe("How a series' value compares with `threshold`. Required for a threshold."),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('The value a series is compared with. Required for a threshold.'),
                        })
                        .describe('When a series is in breach.'),
                })
                .describe('Settings for a metrics alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsCreateBodyTwoGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyTwoGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyTwoGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances. Defaults to mode single.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyTwoEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyTwoEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyTwoDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyTwoDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyTwoCooldownMinutesMin)
                .max(platformAlertsCreateBodyTwoCooldownMinutesMax)
                .default(platformAlertsCreateBodyTwoCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['traces'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyThreeNameMax)
                .default(platformAlertsCreateBodyThreeNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyThreeEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            serviceNames: zod
                                .array(zod.string())
                                .optional()
                                .describe('Services whose requests the alert measures.'),
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
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
                                                                )
                                                                .describe('Person properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
                                                                )
                                                                .describe(
                                                                    'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            cohort_deleted: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort is deleted or does not exist.'
                                                                ),
                                                            cohort_missing: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort does not exist, so it cannot be restored.'
                                                                ),
                                                            cohort_name: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .literal('id')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
                                                                ),
                                                            value: zod.number(),
                                                        }),
                                                        zod.object({
                                                            key: zod.union([
                                                                zod.enum([
                                                                    'duration',
                                                                    'active_seconds',
                                                                    'inactive_seconds',
                                                                ]),
                                                                zod.string(),
                                                            ]),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            group_key_names: zod
                                                                .union([
                                                                    zod.record(zod.string(), zod.string()),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            group_type_index: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional(),
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
                                                                )
                                                                .describe(
                                                                    'Event property with \"$feature\/\" prepended'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
                                                                )
                                                                .describe('Feature flag dependency'),
                                                            value: zod
                                                                .union([zod.boolean(), zod.string()])
                                                                .describe(
                                                                    'The value can be true, false, or a variant name'
                                                                ),
                                                        }),
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            type: zod
                                                                .literal('hogql')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'log',
                                                                'log_attribute',
                                                                'log_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('metric_attribute')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'span',
                                                                'span_attribute',
                                                                'span_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('account_custom_property')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
                                                                )
                                                                .describe(
                                                                    'Customer analytics account custom property — the key is the property definition id'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            event_filters: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod
                                                                                    .union([
                                                                                        zod.enum([
                                                                                            'exact',
                                                                                            'is_not',
                                                                                            'icontains',
                                                                                            'not_icontains',
                                                                                            'starts_with',
                                                                                            'not_starts_with',
                                                                                            'ends_with',
                                                                                            'not_ends_with',
                                                                                            'regex',
                                                                                            'not_regex',
                                                                                            'gt',
                                                                                            'gte',
                                                                                            'lt',
                                                                                            'lte',
                                                                                            'is_set',
                                                                                            'is_not_set',
                                                                                            'is_date_exact',
                                                                                            'is_date_before',
                                                                                            'is_date_after',
                                                                                            'between',
                                                                                            'not_between',
                                                                                            'min',
                                                                                            'max',
                                                                                            'in',
                                                                                            'not_in',
                                                                                            'is_cleaned_path_exact',
                                                                                            'is_cleaned_path_not_exact',
                                                                                            'flag_evaluates_to',
                                                                                            'semver_eq',
                                                                                            'semver_neq',
                                                                                            'semver_gt',
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
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
                                                                                    )
                                                                                    .describe('Event properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
                                                                                    )
                                                                                    .describe('Person properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.enum([
                                                                                    'tag_name',
                                                                                    'text',
                                                                                    'href',
                                                                                    'selector',
                                                                                ]),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
                                                                                    )
                                                                                    .describe(
                                                                                        'Event property with \"$feature\/\" prepended'
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                type: zod
                                                                                    .literal('hogql')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
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
                                                                .optional()
                                                                .describe(
                                                                    'Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral\/cohort filters and groups'
                                                                ),
                                                            event_type: zod.enum(['events', 'actions']),
                                                            explicit_datetime: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Absolute or relative (e.g. -30d) lower date bound — alternative to time_value\/time_interval'
                                                                ),
                                                            explicit_datetime_to: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .string()
                                                                .describe(
                                                                    "Event name, or action id when event_type is 'actions'"
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            negation: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators'
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                .optional()
                                                                .describe(
                                                                    'Count comparison for performed_event_multiple, defaults to exact'
                                                                ),
                                                            operator_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Count threshold for performed_event_multiple'
                                                                ),
                                                            time_interval: zod
                                                                .union([
                                                                    zod.enum(['day', 'week', 'month', 'year']),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            time_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Relative time window size, paired with time_interval'
                                                                ),
                                                            type: zod
                                                                .literal('behavioral')
                                                                .default(
                                                                    platformAlertsCreateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
                                                                )
                                                                .describe(
                                                                    "Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP"
                                                                ),
                                                            value: zod.enum([
                                                                'performed_event',
                                                                'performed_event_multiple',
                                                            ]),
                                                        }),
                                                    ])
                                                ),
                                            })
                                        ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'Span, span attribute and resource attribute filters, as the tracing scene sends.'
                                ),
                        })
                        .optional()
                        .describe('The requests the alert measures.'),
                    condition: zod
                        .object({
                            measure: zod
                                .enum(['request_count', 'error_count', 'error_rate', 'latency'])
                                .describe(
                                    'What the alert measures over requests: their count, the count with an error status, the share with an error status, or a latency percentile. A request is a trace root, server or consumer span.'
                                ),
                            percentile: zod
                                .union([
                                    zod.union([zod.literal(50), zod.literal(90), zod.literal(95), zod.literal(99)]),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('The latency percentile. Required for latency.'),
                            threshold: zod
                                .number()
                                .min(platformAlertsCreateBodyThreeSourceConfigOneConditionThresholdMin)
                                .describe(
                                    'The bound: a count for request_count and error_count, a fraction from 0 to 1 for error_rate, milliseconds for latency.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires above or below it.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes that each check measures.'),
                        })
                        .describe('The bound the measure is checked against.'),
                })
                .describe('Settings for a traces alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsCreateBodyThreeGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyThreeGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyThreeGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances. Defaults to mode single.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyThreeEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyThreeEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyThreeDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyThreeDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyThreeCooldownMinutesMin)
                .max(platformAlertsCreateBodyThreeCooldownMinutesMax)
                .default(platformAlertsCreateBodyThreeCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_destination'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyFourNameMax)
                .default(platformAlertsCreateBodyFourNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyFourEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    destination_ids: zod
                        .array(zod.string())
                        .max(platformAlertsCreateBodyFourSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFourSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_destination alert. The bound the alert is evaluated against is under condition.'
                ),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsCreateBodyFourGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyFourGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyFourGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances. Defaults to mode single.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFourEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyFourEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFourDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyFourDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyFourCooldownMinutesMin)
                .max(platformAlertsCreateBodyFourCooldownMinutesMax)
                .default(platformAlertsCreateBodyFourCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyFiveNameMax)
                .default(platformAlertsCreateBodyFiveNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyFiveEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.string())
                        .max(platformAlertsCreateBodyFiveSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsCreateBodyFiveSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFiveSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_source alert. The bound the alert is evaluated against is under condition.'
                ),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsCreateBodyFiveGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyFiveGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyFiveGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances. Defaults to mode single.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFiveEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyFiveEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFiveDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyFiveDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyFiveCooldownMinutesMin)
                .max(platformAlertsCreateBodyFiveCooldownMinutesMax)
                .default(platformAlertsCreateBodyFiveCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
])

/**
 * Get one alert with the runtime state of each of its groups.
 * @summary Get an alert
 */
export const PlatformAlertsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Change some settings of an alert the platform owns. Settings left out keep their stored value. A source_kind that is sent must match the stored value.
 * @summary Change an alert
 */
export const PlatformAlertsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const platformAlertsPartialUpdateBodyOneNameMax = 255

export const platformAlertsPartialUpdateBodyOneSourceConfigOneSkipWeekendDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault = 0
export const platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin = 0

export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault = `notify`
export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyTwoNameMax = 255

export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyTwoEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyTwoDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyThreeNameMax = 255

export const platformAlertsPartialUpdateBodyThreeSourceConfigOneQueryMax = 10000

export const platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyThreeEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyThreeDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFourNameMax = 255

export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsPartialUpdateBodyFourSourceConfigOneConditionThresholdMin = 0

export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFourEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyFourDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyFourCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFiveNameMax = 255

export const platformAlertsPartialUpdateBodyFiveSourceConfigOneDestinationIdsMax = 100

export const platformAlertsPartialUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFiveEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyFiveDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodySixNameMax = 255

export const platformAlertsPartialUpdateBodySixSourceConfigOneSourceIdsMax = 100

export const platformAlertsPartialUpdateBodySixSourceConfigOneGroupByDefault = `source`
export const platformAlertsPartialUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsPartialUpdateBodySixSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodySixGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodySixEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodySixDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodySixCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodySixCooldownMinutesMax = 2147483647

export const PlatformAlertsPartialUpdateBody = () => zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['insight'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyOneNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    insight_id: zod
                        .number()
                        .describe('The insight the alert checks. It cannot change through this API.'),
                    condition: zod
                        .object({
                            threshold: zod
                                .union([
                                    zod.object({
                                        bounds: zod
                                            .union([
                                                zod.object({
                                                    lower: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Alert fires when the value drops below this number.'
                                                        ),
                                                    upper: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe('Alert fires when the value exceeds this number.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        type: zod
                                            .enum(['absolute', 'percentage'])
                                            .describe(
                                                'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .describe(
                                    "The bounds the insight's value is checked against, absolute or as a percentage change."
                                ),
                            comparison: zod
                                .object({
                                    type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
                                })
                                .describe(
                                    'How the value is compared: as it is, or as an increase or decrease from the previous interval.'
                                ),
                            detector: zod
                                .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                                .optional()
                                .describe(
                                    "The anomaly detector the alert uses in place of its threshold, or null for a threshold alert. It can't change through this API."
                                ),
                        })
                        .describe("The bound the insight's value is checked against."),
                    config: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .optional()
                        .describe(
                            "Which part of the insight the alert reads, such as the series and whether the current interval counts. It can't change through this API."
                        ),
                    skip_weekend: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneSkipWeekendDefault)
                        .describe("Whether checks skip Saturdays and Sundays. It can't change through this API."),
                    evaluation_delay_intervals: zod
                        .number()
                        .min(platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin)
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault)
                        .describe(
                            "How many of the most recent intervals a check leaves out, so late data can arrive. It can't change through this API."
                        ),
                    investigation_agent_enabled: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault)
                        .describe(
                            "Whether an AI agent investigates each firing of an anomaly alert. It can't change through this API."
                        ),
                    investigation_gates_notifications: zod
                        .boolean()
                        .default(
                            platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault
                        )
                        .describe(
                            "Whether a firing waits for the agent's verdict, and is dropped when the agent calls it a false positive. It can't change through this API."
                        ),
                    investigation_inconclusive_action: zod
                        .enum(['notify', 'suppress'])
                        .default(
                            platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault
                        )
                        .describe(
                            "What a waiting firing does when the agent's verdict is inconclusive. It can't change through this API."
                        ),
                })
                .optional()
                .describe('Settings for a insight alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyOneCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyOneCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['logs'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyTwoNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
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
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
                                                                )
                                                                .describe('Person properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
                                                                )
                                                                .describe(
                                                                    'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            cohort_deleted: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort is deleted or does not exist.'
                                                                ),
                                                            cohort_missing: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort does not exist, so it cannot be restored.'
                                                                ),
                                                            cohort_name: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .literal('id')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
                                                                ),
                                                            value: zod.number(),
                                                        }),
                                                        zod.object({
                                                            key: zod.union([
                                                                zod.enum([
                                                                    'duration',
                                                                    'active_seconds',
                                                                    'inactive_seconds',
                                                                ]),
                                                                zod.string(),
                                                            ]),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            group_key_names: zod
                                                                .union([
                                                                    zod.record(zod.string(), zod.string()),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            group_type_index: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional(),
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
                                                                )
                                                                .describe(
                                                                    'Event property with \"$feature\/\" prepended'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
                                                                )
                                                                .describe('Feature flag dependency'),
                                                            value: zod
                                                                .union([zod.boolean(), zod.string()])
                                                                .describe(
                                                                    'The value can be true, false, or a variant name'
                                                                ),
                                                        }),
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            type: zod
                                                                .literal('hogql')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'log',
                                                                'log_attribute',
                                                                'log_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('metric_attribute')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'span',
                                                                'span_attribute',
                                                                'span_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('account_custom_property')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
                                                                )
                                                                .describe(
                                                                    'Customer analytics account custom property — the key is the property definition id'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            event_filters: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod
                                                                                    .union([
                                                                                        zod.enum([
                                                                                            'exact',
                                                                                            'is_not',
                                                                                            'icontains',
                                                                                            'not_icontains',
                                                                                            'starts_with',
                                                                                            'not_starts_with',
                                                                                            'ends_with',
                                                                                            'not_ends_with',
                                                                                            'regex',
                                                                                            'not_regex',
                                                                                            'gt',
                                                                                            'gte',
                                                                                            'lt',
                                                                                            'lte',
                                                                                            'is_set',
                                                                                            'is_not_set',
                                                                                            'is_date_exact',
                                                                                            'is_date_before',
                                                                                            'is_date_after',
                                                                                            'between',
                                                                                            'not_between',
                                                                                            'min',
                                                                                            'max',
                                                                                            'in',
                                                                                            'not_in',
                                                                                            'is_cleaned_path_exact',
                                                                                            'is_cleaned_path_not_exact',
                                                                                            'flag_evaluates_to',
                                                                                            'semver_eq',
                                                                                            'semver_neq',
                                                                                            'semver_gt',
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
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
                                                                                    )
                                                                                    .describe('Event properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
                                                                                    )
                                                                                    .describe('Person properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.enum([
                                                                                    'tag_name',
                                                                                    'text',
                                                                                    'href',
                                                                                    'selector',
                                                                                ]),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
                                                                                    )
                                                                                    .describe(
                                                                                        'Event property with \"$feature\/\" prepended'
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                type: zod
                                                                                    .literal('hogql')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
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
                                                                .optional()
                                                                .describe(
                                                                    'Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral\/cohort filters and groups'
                                                                ),
                                                            event_type: zod.enum(['events', 'actions']),
                                                            explicit_datetime: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Absolute or relative (e.g. -30d) lower date bound — alternative to time_value\/time_interval'
                                                                ),
                                                            explicit_datetime_to: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .string()
                                                                .describe(
                                                                    "Event name, or action id when event_type is 'actions'"
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            negation: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators'
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                .optional()
                                                                .describe(
                                                                    'Count comparison for performed_event_multiple, defaults to exact'
                                                                ),
                                                            operator_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Count threshold for performed_event_multiple'
                                                                ),
                                                            time_interval: zod
                                                                .union([
                                                                    zod.enum(['day', 'week', 'month', 'year']),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            time_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Relative time window size, paired with time_interval'
                                                                ),
                                                            type: zod
                                                                .literal('behavioral')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
                                                                )
                                                                .describe(
                                                                    "Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP"
                                                                ),
                                                            value: zod.enum([
                                                                'performed_event',
                                                                'performed_event_multiple',
                                                            ]),
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
                                .union([
                                    zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])),
                                    zod.null(),
                                ])
                                .optional(),
                        })
                        .describe(
                            'The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one.'
                        ),
                    condition: zod
                        .object({
                            threshold_count: zod
                                .number()
                                .min(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMax)
                                .describe(
                                    'Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires when the count is above or below the threshold.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes over which logs are counted.'),
                        })
                        .describe('The bound the count is checked against.'),
                })
                .optional()
                .describe('Settings for a logs alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyTwoGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyTwoEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyTwoDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyTwoCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyTwoCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['metrics'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyThreeNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyThreeSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionKindDefault)
                                .describe(
                                    "threshold compares each series' latest value with `threshold`. present fires for every series the query returns, for a query that already filters to the series in breach."
                                ),
                            operator: zod
                                .union([zod.enum(['gt', 'gte', 'lt', 'lte', 'eq', 'ne']), zod.null()])
                                .optional()
                                .describe("How a series' value compares with `threshold`. Required for a threshold."),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('The value a series is compared with. Required for a threshold.'),
                        })
                        .describe('When a series is in breach.'),
                })
                .optional()
                .describe('Settings for a metrics alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyThreeGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyThreeEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyThreeDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyThreeCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyThreeCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['traces'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyFourNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            serviceNames: zod
                                .array(zod.string())
                                .optional()
                                .describe('Services whose requests the alert measures.'),
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
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
                                                                )
                                                                .describe('Person properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
                                                                )
                                                                .describe(
                                                                    'Top-level columns on the persons table (e.g. created_at), not properties JSON'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            cohort_deleted: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort is deleted or does not exist.'
                                                                ),
                                                            cohort_missing: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Set by the feature flag API when the cohort does not exist, so it cannot be restored.'
                                                                ),
                                                            cohort_name: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .literal('id')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
                                                                ),
                                                            value: zod.number(),
                                                        }),
                                                        zod.object({
                                                            key: zod.union([
                                                                zod.enum([
                                                                    'duration',
                                                                    'active_seconds',
                                                                    'inactive_seconds',
                                                                ]),
                                                                zod.string(),
                                                            ]),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            group_key_names: zod
                                                                .union([
                                                                    zod.record(zod.string(), zod.string()),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            group_type_index: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional(),
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            operator: zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
                                                                )
                                                                .describe(
                                                                    'Event property with \"$feature\/\" prepended'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
                                                                )
                                                                .describe('Feature flag dependency'),
                                                            value: zod
                                                                .union([zod.boolean(), zod.string()])
                                                                .describe(
                                                                    'The value can be true, false, or a variant name'
                                                                ),
                                                        }),
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            type: zod
                                                                .literal('hogql')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'log',
                                                                'log_attribute',
                                                                'log_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('metric_attribute')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod.enum([
                                                                'span',
                                                                'span_attribute',
                                                                'span_resource_attribute',
                                                            ]),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            type: zod
                                                                .literal('account_custom_property')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
                                                                )
                                                                .describe(
                                                                    'Customer analytics account custom property — the key is the property definition id'
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
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
                                                                'starts_with',
                                                                'not_starts_with',
                                                                'ends_with',
                                                                'not_ends_with',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'is_cleaned_path_not_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
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
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
                                                                ),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                        }),
                                                        zod.object({
                                                            event_filters: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod
                                                                                    .union([
                                                                                        zod.enum([
                                                                                            'exact',
                                                                                            'is_not',
                                                                                            'icontains',
                                                                                            'not_icontains',
                                                                                            'starts_with',
                                                                                            'not_starts_with',
                                                                                            'ends_with',
                                                                                            'not_ends_with',
                                                                                            'regex',
                                                                                            'not_regex',
                                                                                            'gt',
                                                                                            'gte',
                                                                                            'lt',
                                                                                            'lte',
                                                                                            'is_set',
                                                                                            'is_not_set',
                                                                                            'is_date_exact',
                                                                                            'is_date_before',
                                                                                            'is_date_after',
                                                                                            'between',
                                                                                            'not_between',
                                                                                            'min',
                                                                                            'max',
                                                                                            'in',
                                                                                            'not_in',
                                                                                            'is_cleaned_path_exact',
                                                                                            'is_cleaned_path_not_exact',
                                                                                            'flag_evaluates_to',
                                                                                            'semver_eq',
                                                                                            'semver_neq',
                                                                                            'semver_gt',
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
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
                                                                                    )
                                                                                    .describe('Event properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
                                                                                    )
                                                                                    .describe('Person properties'),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.enum([
                                                                                    'tag_name',
                                                                                    'text',
                                                                                    'href',
                                                                                    'selector',
                                                                                ]),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                operator: zod.enum([
                                                                                    'exact',
                                                                                    'is_not',
                                                                                    'icontains',
                                                                                    'not_icontains',
                                                                                    'starts_with',
                                                                                    'not_starts_with',
                                                                                    'ends_with',
                                                                                    'not_ends_with',
                                                                                    'regex',
                                                                                    'not_regex',
                                                                                    'gt',
                                                                                    'gte',
                                                                                    'lt',
                                                                                    'lte',
                                                                                    'is_set',
                                                                                    'is_not_set',
                                                                                    'is_date_exact',
                                                                                    'is_date_before',
                                                                                    'is_date_after',
                                                                                    'between',
                                                                                    'not_between',
                                                                                    'min',
                                                                                    'max',
                                                                                    'in',
                                                                                    'not_in',
                                                                                    'is_cleaned_path_exact',
                                                                                    'is_cleaned_path_not_exact',
                                                                                    'flag_evaluates_to',
                                                                                    'semver_eq',
                                                                                    'semver_neq',
                                                                                    'semver_gt',
                                                                                    'semver_gte',
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
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
                                                                                    )
                                                                                    .describe(
                                                                                        'Event property with \"$feature\/\" prepended'
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
                                                                                        zod.string(),
                                                                                        zod.number(),
                                                                                        zod.boolean(),
                                                                                        zod.null(),
                                                                                    ])
                                                                                    .optional(),
                                                                            }),
                                                                            zod.object({
                                                                                key: zod.string(),
                                                                                label: zod
                                                                                    .union([zod.string(), zod.null()])
                                                                                    .optional(),
                                                                                type: zod
                                                                                    .literal('hogql')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
                                                                                    ),
                                                                                value: zod
                                                                                    .union([
                                                                                        zod.array(
                                                                                            zod.union([
                                                                                                zod.string(),
                                                                                                zod.number(),
                                                                                                zod.boolean(),
                                                                                            ])
                                                                                        ),
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
                                                                .optional()
                                                                .describe(
                                                                    'Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral\/cohort filters and groups'
                                                                ),
                                                            event_type: zod.enum(['events', 'actions']),
                                                            explicit_datetime: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Absolute or relative (e.g. -30d) lower date bound — alternative to time_value\/time_interval'
                                                                ),
                                                            explicit_datetime_to: zod
                                                                .union([zod.string(), zod.null()])
                                                                .optional(),
                                                            key: zod
                                                                .string()
                                                                .describe(
                                                                    "Event name, or action id when event_type is 'actions'"
                                                                ),
                                                            label: zod.union([zod.string(), zod.null()]).optional(),
                                                            negation: zod
                                                                .union([zod.boolean(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators'
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'starts_with',
                                                                        'not_starts_with',
                                                                        'ends_with',
                                                                        'not_ends_with',
                                                                        'regex',
                                                                        'not_regex',
                                                                        'gt',
                                                                        'gte',
                                                                        'lt',
                                                                        'lte',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'is_date_exact',
                                                                        'is_date_before',
                                                                        'is_date_after',
                                                                        'between',
                                                                        'not_between',
                                                                        'min',
                                                                        'max',
                                                                        'in',
                                                                        'not_in',
                                                                        'is_cleaned_path_exact',
                                                                        'is_cleaned_path_not_exact',
                                                                        'flag_evaluates_to',
                                                                        'semver_eq',
                                                                        'semver_neq',
                                                                        'semver_gt',
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
                                                                .optional()
                                                                .describe(
                                                                    'Count comparison for performed_event_multiple, defaults to exact'
                                                                ),
                                                            operator_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Count threshold for performed_event_multiple'
                                                                ),
                                                            time_interval: zod
                                                                .union([
                                                                    zod.enum(['day', 'week', 'month', 'year']),
                                                                    zod.null(),
                                                                ])
                                                                .optional(),
                                                            time_value: zod
                                                                .union([zod.number(), zod.null()])
                                                                .optional()
                                                                .describe(
                                                                    'Relative time window size, paired with time_interval'
                                                                ),
                                                            type: zod
                                                                .literal('behavioral')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
                                                                )
                                                                .describe(
                                                                    "Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP"
                                                                ),
                                                            value: zod.enum([
                                                                'performed_event',
                                                                'performed_event_multiple',
                                                            ]),
                                                        }),
                                                    ])
                                                ),
                                            })
                                        ),
                                    }),
                                    zod.null(),
                                ])
                                .optional()
                                .describe(
                                    'Span, span attribute and resource attribute filters, as the tracing scene sends.'
                                ),
                        })
                        .optional()
                        .describe('The requests the alert measures.'),
                    condition: zod
                        .object({
                            measure: zod
                                .enum(['request_count', 'error_count', 'error_rate', 'latency'])
                                .describe(
                                    'What the alert measures over requests: their count, the count with an error status, the share with an error status, or a latency percentile. A request is a trace root, server or consumer span.'
                                ),
                            percentile: zod
                                .union([
                                    zod.union([zod.literal(50), zod.literal(90), zod.literal(95), zod.literal(99)]),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('The latency percentile. Required for latency.'),
                            threshold: zod
                                .number()
                                .min(platformAlertsPartialUpdateBodyFourSourceConfigOneConditionThresholdMin)
                                .describe(
                                    'The bound: a count for request_count and error_count, a fraction from 0 to 1 for error_rate, milliseconds for latency.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires above or below it.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes that each check measures.'),
                        })
                        .describe('The bound the measure is checked against.'),
                })
                .optional()
                .describe('Settings for a traces alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyFourGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFourEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFourDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyFourCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyFourCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_destination'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyFiveNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    destination_ids: zod
                        .array(zod.string())
                        .max(platformAlertsPartialUpdateBodyFiveSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .optional()
                .describe(
                    'Settings for a warehouse_destination alert. The bound the alert is evaluated against is under condition.'
                ),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyFiveGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFiveEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFiveDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyFiveCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyFiveCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodySixNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.string())
                        .max(platformAlertsPartialUpdateBodySixSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .optional()
                .describe(
                    'Settings for a warehouse_source alert. The bound the alert is evaluated against is under condition.'
                ),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodySixGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodySixEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodySixDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodySixCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodySixCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
])

/**
 * Delete an alert the platform owns, with its destinations.
 * @summary Delete an alert
 */
export const PlatformAlertsDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List the notification destinations of a warehouse alert.
 */
export const WarehouseAlertsDestinationsListParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Add a notification destination to a warehouse alert.
 */
export const WarehouseAlertsDestinationsCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseAlertsDestinationsCreateBodyPagerdutySeverityDefault = `critical`
export const warehouseAlertsDestinationsCreateBodyPagerdutyRegionDefault = `us`

export const WarehouseAlertsDestinationsCreateBody = () => zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord', 'pagerduty'])
        .describe(
            '\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams\n\* `discord` - discord\n\* `pagerduty` - pagerduty'
        )
        .describe(
            'Notification destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams\n\* `discord` - discord\n\* `pagerduty` - pagerduty'
        ),
    event_kinds: zod
        .array(zod.enum(['firing', 'resolved']).describe('\* `firing` - firing\n\* `resolved` - resolved'))
        .min(1)
        .default([`firing`, `resolved`])
        .describe(
            'Which transitions send a message. A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves, whatever this lists. Defaults to every kind.'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required for webhook, teams and discord.'),
    pagerduty_routing_key: zod
        .string()
        .optional()
        .describe('Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.'),
    pagerduty_severity: zod
        .enum(['critical', 'error', 'warning', 'info'])
        .describe('\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info')
        .default(warehouseAlertsDestinationsCreateBodyPagerdutySeverityDefault)
        .describe(
            'Severity PagerDuty records on the incident. Used when type=pagerduty.\n\n\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info'
        ),
    pagerduty_region: zod
        .enum(['us', 'eu'])
        .describe('\* `us` - us\n\* `eu` - eu')
        .default(warehouseAlertsDestinationsCreateBodyPagerdutyRegionDefault)
        .describe('PagerDuty service region of the account. Used when type=pagerduty.\n\n\* `us` - us\n\* `eu` - eu'),
})

/**
 * Delete notification destinations of a warehouse alert.
 */
export const WarehouseAlertsDestinationsDeleteCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseAlertsDestinationsDeleteCreateBodyDestinationIdsMax = 5

export const WarehouseAlertsDestinationsDeleteCreateBody = () => zod.object({
    destination_ids: zod
        .array(zod.string())
        .min(1)
        .max(warehouseAlertsDestinationsDeleteCreateBodyDestinationIdsMax)
        .describe("IDs of the alert's destinations to delete, as the list endpoint returns them."),
})
