/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
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
        .enum(['logs', 'insight', 'warehouse_source', 'warehouse_destination', 'metrics', 'traces', 'error_tracking'])
        .optional()
        .describe(
            'Only alerts of this source kind, such as metrics. A kind the caller cannot read returns no alerts.\n\n\* `logs` - Logs\n\* `insight` - Insight\n\* `warehouse_source` - Warehouse source\n\* `warehouse_destination` - Warehouse destination\n\* `metrics` - Metrics\n\* `traces` - Traces\n\* `error_tracking` - Error tracking'
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
export const platformAlertsCreateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyOneEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyOneEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodyOneDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyOneDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodyOneCooldownMinutesDefault = 0
export const platformAlertsCreateBodyOneCooldownMinutesMin = 0
export const platformAlertsCreateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyTwoNameDefault = `Untitled alert`
export const platformAlertsCreateBodyTwoNameMax = 255

export const platformAlertsCreateBodyTwoEnabledDefault = true
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsCreateBodyTwoSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsCreateBodyTwoSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyTwoEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyTwoEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodyTwoDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyTwoDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodyTwoCooldownMinutesDefault = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMin = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyThreeNameDefault = `Untitled alert`
export const platformAlertsCreateBodyThreeNameMax = 255

export const platformAlertsCreateBodyThreeEnabledDefault = true
export const platformAlertsCreateBodyThreeSourceConfigOneQueryMax = 10000

export const platformAlertsCreateBodyThreeSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyThreeEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyThreeEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodyThreeDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyThreeDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodyThreeCooldownMinutesDefault = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMin = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFourNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFourNameMax = 255

export const platformAlertsCreateBodyFourEnabledDefault = true
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsCreateBodyFourSourceConfigOneConditionThresholdMin = 0

export const platformAlertsCreateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFourEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFourEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodyFourDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFourDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodyFourCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFourCooldownMinutesMin = 0
export const platformAlertsCreateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFiveNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFiveNameMax = 255

export const platformAlertsCreateBodyFiveEnabledDefault = true
export const platformAlertsCreateBodyFiveSourceConfigOneDestinationIdsMax = 100

export const platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFiveEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFiveEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodyFiveDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFiveDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodyFiveCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMin = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodySixNameDefault = `Untitled alert`
export const platformAlertsCreateBodySixNameMax = 255

export const platformAlertsCreateBodySixEnabledDefault = true
export const platformAlertsCreateBodySixSourceConfigOneSourceIdsMax = 100

export const platformAlertsCreateBodySixSourceConfigOneGroupByDefault = `source`
export const platformAlertsCreateBodySixSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsCreateBodySixSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodySixGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodySixGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodySixGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodySixEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodySixEvaluationPeriodsMax = 1441

export const platformAlertsCreateBodySixDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodySixDatapointsToAlarmMax = 1441

export const platformAlertsCreateBodySixCooldownMinutesDefault = 0
export const platformAlertsCreateBodySixCooldownMinutesMin = 0
export const platformAlertsCreateBodySixCooldownMinutesMax = 2147483647

export const PlatformAlertsCreateBody = () => zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['error_tracking'])
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
                            properties: zod
                                .array(zod.record(zod.string(), zod.unknown()))
                                .optional()
                                .describe('Property filters on the exception event. Every filter must match.'),
                        })
                        .optional()
                        .describe('The issues and exceptions the alert announces.'),
                    condition: zod
                        .object({
                            triggers: zod
                                .array(zod.enum(['issue_created', 'issue_reopened', 'issue_assigned']))
                                .min(1)
                                .describe(
                                    'The issue changes the alert announces. Each matching change is announced once.'
                                ),
                        })
                        .describe('The issue changes the alert announces.'),
                })
                .describe(
                    'Settings for a error_tracking alert. The bound the alert is evaluated against is under condition.'
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
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
                .enum(['logs'])
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
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
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
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
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
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
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
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
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
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
                                                                                        platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
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
                                                                    platformAlertsCreateBodyTwoSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
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
                                .min(platformAlertsCreateBodyTwoSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsCreateBodyTwoSourceConfigOneConditionThresholdCountMax)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
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
                .enum(['metrics'])
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
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsCreateBodyThreeSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsCreateBodyThreeSourceConfigOneConditionKindDefault)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
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
            check_interval_minutes: zod
                .number()
                .min(1)
                .optional()
                .describe(
                    'Minutes between scheduled checks. One of: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60. Defaults to 1 on a create. An edit that leaves it out keeps the stored value.'
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
                .max(platformAlertsCreateBodyFourNameMax)
                .default(platformAlertsCreateBodyFourNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyFourEnabledDefault)
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
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
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
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
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
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
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
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
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
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
                                                                                        platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
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
                                                                    platformAlertsCreateBodyFourSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
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
                                .min(platformAlertsCreateBodyFourSourceConfigOneConditionThresholdMin)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
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
                .enum(['warehouse_destination'])
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
                    destination_ids: zod
                        .array(zod.string())
                        .max(platformAlertsCreateBodyFiveSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
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
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodySixNameMax)
                .default(platformAlertsCreateBodySixNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodySixEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.string())
                        .max(platformAlertsCreateBodySixSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsCreateBodySixSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsCreateBodySixSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodySixSourceConfigOneEmailProjectMembersDefault)
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
                        .max(platformAlertsCreateBodySixGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodySixGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodySixGroupingOneOnOverflowDefault)
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
                .max(platformAlertsCreateBodySixEvaluationPeriodsMax)
                .default(platformAlertsCreateBodySixEvaluationPeriodsDefault)
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441. Defaults to 1.'
                ),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodySixDatapointsToAlarmMax)
                .default(platformAlertsCreateBodySixDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodySixCooldownMinutesMin)
                .max(platformAlertsCreateBodySixCooldownMinutesMax)
                .default(platformAlertsCreateBodySixCooldownMinutesDefault)
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

export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyTwoNameMax = 255

export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdNameDefault = ``
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdNameMax = 255

export const platformAlertsPartialUpdateBodyTwoSourceConfigOneSkipWeekendDefault = false
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneEvaluationDelayIntervalsDefault = 0
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneEvaluationDelayIntervalsMin = 0

export const platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationAgentEnabledDefault = false
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationGatesNotificationsDefault = false
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationInconclusiveActionDefault = `notify`
export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyTwoEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodyTwoDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyThreeNameMax = 255

export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyThreeEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodyThreeDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFourNameMax = 255

export const platformAlertsPartialUpdateBodyFourSourceConfigOneQueryMax = 10000

export const platformAlertsPartialUpdateBodyFourSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFourEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodyFourDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodyFourCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFiveNameMax = 255

export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault = `event`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault = `person`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault = `person_metadata`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault = `element`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault = `event_metadata`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault = `session`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault = `id`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault = `in`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault = `cohort`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault = `recording`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault = `log_entry`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault = `group`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault = `flag_evaluates_to`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault = `flag`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault = `empty`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault = `data_warehouse`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault = `data_warehouse_person_property`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault = `error_tracking_issue`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault = `metric_attribute`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault = `revenue_analytics`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault = `account_custom_property`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault = `workflow_variable`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault = `exact`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault = `event`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault = `person`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault = `element`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault = `feature`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault = `hogql`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault = `behavioral`
export const platformAlertsPartialUpdateBodyFiveSourceConfigOneConditionThresholdMin = 0

export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFiveEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodyFiveDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodySixNameMax = 255

export const platformAlertsPartialUpdateBodySixSourceConfigOneDestinationIdsMax = 100

export const platformAlertsPartialUpdateBodySixSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodySixGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodySixEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodySixDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodySixCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodySixCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodySevenNameMax = 255

export const platformAlertsPartialUpdateBodySevenSourceConfigOneSourceIdsMax = 100

export const platformAlertsPartialUpdateBodySevenSourceConfigOneGroupByDefault = `source`
export const platformAlertsPartialUpdateBodySevenSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsPartialUpdateBodySevenSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodySevenGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodySevenGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodySevenGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodySevenEvaluationPeriodsMax = 1441

export const platformAlertsPartialUpdateBodySevenDatapointsToAlarmMax = 1441

export const platformAlertsPartialUpdateBodySevenCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodySevenCooldownMinutesMax = 2147483647

export const PlatformAlertsPartialUpdateBody = () => zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['error_tracking'])
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
                    filters: zod
                        .object({
                            properties: zod
                                .array(zod.record(zod.string(), zod.unknown()))
                                .optional()
                                .describe('Property filters on the exception event. Every filter must match.'),
                        })
                        .optional()
                        .describe('The issues and exceptions the alert announces.'),
                    condition: zod
                        .object({
                            triggers: zod
                                .array(zod.enum(['issue_created', 'issue_reopened', 'issue_assigned']))
                                .min(1)
                                .describe(
                                    'The issue changes the alert announces. Each matching change is announced once.'
                                ),
                        })
                        .describe('The issue changes the alert announces.'),
                })
                .optional()
                .describe(
                    'Settings for a error_tracking alert. The bound the alert is evaluated against is under condition.'
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
                .enum(['insight'])
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
                            threshold_name: zod
                                .string()
                                .max(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdNameMax)
                                .default(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdNameDefault)
                                .describe("The threshold's name, shown with its bounds on the insight."),
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
                        .default(platformAlertsPartialUpdateBodyTwoSourceConfigOneSkipWeekendDefault)
                        .describe("Whether checks skip Saturdays and Sundays. It can't change through this API."),
                    evaluation_delay_intervals: zod
                        .number()
                        .min(platformAlertsPartialUpdateBodyTwoSourceConfigOneEvaluationDelayIntervalsMin)
                        .default(platformAlertsPartialUpdateBodyTwoSourceConfigOneEvaluationDelayIntervalsDefault)
                        .describe(
                            "How many of the most recent intervals a check leaves out, so late data can arrive. It can't change through this API."
                        ),
                    investigation_agent_enabled: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationAgentEnabledDefault)
                        .describe(
                            "Whether an AI agent investigates each firing of an anomaly alert. It can't change through this API."
                        ),
                    investigation_gates_notifications: zod
                        .boolean()
                        .default(
                            platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationGatesNotificationsDefault
                        )
                        .describe(
                            "Whether a firing waits for the agent's verdict, and is dropped when the agent calls it a false positive. It can't change through this API."
                        ),
                    investigation_inconclusive_action: zod
                        .enum(['notify', 'suppress'])
                        .default(
                            platformAlertsPartialUpdateBodyTwoSourceConfigOneInvestigationInconclusiveActionDefault
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
                .enum(['logs'])
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyThreeSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
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
                                .min(platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionThresholdCountMax)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
                .enum(['metrics'])
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
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyFourSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsPartialUpdateBodyFourSourceConfigOneConditionKindDefault)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
            check_interval_minutes: zod
                .number()
                .min(1)
                .optional()
                .describe(
                    'Minutes between scheduled checks. One of: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60. Defaults to 1 on a create. An edit that leaves it out keeps the stored value.'
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
                .max(platformAlertsPartialUpdateBodyFiveNameMax)
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemThreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFourTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemFiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSixTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemSevenTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightKeyDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('cohort')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemEightTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemNineTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnezeroTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneoneTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnetwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeOperatorDefault
                                                                )
                                                                .describe(
                                                                    'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                                ),
                                                            type: zod
                                                                .literal('flag')
                                                                .default(
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnethreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefourTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnefiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesixTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOnesevenTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemOneeightTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwozeroTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwotwoTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwothreeTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofourTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneOperatorDefault
                                                                                    ),
                                                                                type: zod
                                                                                    .literal('event')
                                                                                    .default(
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemOneTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemTwoTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemThreeTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFourTypeDefault
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
                                                                                        platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveEventFiltersOneItemFiveTypeDefault
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
                                                                    platformAlertsPartialUpdateBodyFiveSourceConfigOneFiltersFilterGroupOneValuesItemValuesItemTwofiveTypeDefault
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
                                .min(platformAlertsPartialUpdateBodyFiveSourceConfigOneConditionThresholdMin)
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
                .enum(['warehouse_destination'])
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
                    destination_ids: zod
                        .array(zod.string())
                        .max(platformAlertsPartialUpdateBodySixSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
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
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
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
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodySevenNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.string())
                        .max(platformAlertsPartialUpdateBodySevenSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsPartialUpdateBodySevenSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySevenSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySevenSourceConfigOneEmailProjectMembersDefault)
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
                        .max(platformAlertsPartialUpdateBodySevenGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodySevenGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodySevenGroupingOneOnOverflowDefault)
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
                .max(platformAlertsPartialUpdateBodySevenEvaluationPeriodsMax)
                .optional()
                .describe(
                    'Number of recent checks considered when deciding to fire. Most source kinds allow up to 10; metrics alerts allow up to 1441.'
                ),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodySevenDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodySevenCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodySevenCooldownMinutesMax)
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
