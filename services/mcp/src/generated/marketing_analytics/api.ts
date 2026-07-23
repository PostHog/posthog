/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read the configured conversion goals for the current project — each with its kind, target, last-30d count, integrated vs non-integrated split, and a misconfiguration flag. Read-only.
 * @summary List conversion goals
 */
export const MarketingAnalyticsConversionGoalsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Remove one conversion goal from the project, leaving the others in place.
 * @summary Delete conversion goal
 */
export const MarketingAnalyticsConversionGoalsDeleteDestroyParams = /* @__PURE__ */ zod.object({
    conversion_goal_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are kept, and the goal keeps its position in the list.
 * @summary Update conversion goal
 */
export const MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams = /* @__PURE__ */ zod.object({
    conversion_goal_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneKindDefault = `EventsNode`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoKindDefault = `ActionsNode`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeKindDefault = `DataWarehouseNode`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwotwoTypeDefault = `workflow_variable`

export const MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody = /* @__PURE__ */ zod.object({
    goal: zod
        .union([
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                event: zod.union([zod.string(), zod.null()]).optional().describe('The event or `null` for all events.'),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                kind: zod
                    .literal('EventsNode')
                    .default(marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOneKindDefault),
                limit: zod.union([zod.number(), zod.null()]).optional(),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
                orderBy: zod
                    .union([zod.array(zod.string()), zod.null()])
                    .optional()
                    .describe('Columns to order by'),
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneOnePropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                id: zod.number(),
                kind: zod
                    .literal('ActionsNode')
                    .default(marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoKindDefault),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneTwoPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                distinct_id_field: zod.string(),
                dw_source_type: zod.union([zod.string(), zod.null()]).optional(),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                id: zod.string(),
                id_field: zod.string(),
                kind: zod
                    .literal('DataWarehouseNode')
                    .default(marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreeKindDefault),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsUpdatePartialUpdateBodyGoalOneThreePropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                table_name: zod.string(),
                timestamp_field: zod.string(),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
        ])
        .describe('Wrapper for OpenAPI schema generation - one goal, in any of the three node shapes.')
        .optional()
        .describe(
            'The conversion goal. Must match one of the ConversionGoalFilter shapes: an events node, an actions node or a data warehouse node. On create, conversion_goal_id is assigned by the server and any value sent is ignored. On update, only the fields you send are changed.'
        ),
})

/**
 * Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.
 * @summary Create conversion goal
 */
export const MarketingAnalyticsConversionGoalsCreateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneKindDefault = `EventsNode`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoKindDefault = `ActionsNode`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwotwoTypeDefault = `workflow_variable`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeKindDefault = `DataWarehouseNode`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneOperatorDefault = `exact`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneTypeDefault = `event`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwoTypeDefault = `person`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemThreeTypeDefault = `person_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemFourTypeDefault = `element`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemFiveTypeDefault = `event_metadata`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSixTypeDefault = `session`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenKeyDefault = `id`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenOperatorDefault = `in`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenTypeDefault = `cohort`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemEightTypeDefault = `recording`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemNineTypeDefault = `log_entry`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnezeroTypeDefault = `group`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneoneTypeDefault = `feature`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnetwoOperatorDefault = `flag_evaluates_to`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnetwoTypeDefault = `flag`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnethreeTypeDefault = `hogql`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnefourTypeDefault = `empty`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnefiveTypeDefault = `data_warehouse`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnesixTypeDefault = `data_warehouse_person_property`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnesevenTypeDefault = `error_tracking_issue`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnenineTypeDefault = `metric_attribute`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwooneTypeDefault = `revenue_analytics`
export const marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwotwoTypeDefault = `workflow_variable`

export const MarketingAnalyticsConversionGoalsCreateCreateBody = /* @__PURE__ */ zod.object({
    goal: zod
        .union([
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                event: zod.union([zod.string(), zod.null()]).optional().describe('The event or `null` for all events.'),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                kind: zod
                    .literal('EventsNode')
                    .default(marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOneKindDefault),
                limit: zod.union([zod.number(), zod.null()]).optional(),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
                orderBy: zod
                    .union([zod.array(zod.string()), zod.null()])
                    .optional()
                    .describe('Columns to order by'),
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneOnePropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                id: zod.number(),
                kind: zod
                    .literal('ActionsNode')
                    .default(marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoKindDefault),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneTwoPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
            zod.object({
                conversion_goal_id: zod.string(),
                conversion_goal_name: zod.string(),
                counts_as_customer: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as customer-defining: a conversion here means the person became a customer (e.g. a payment or subscription), not an intermediate step like a sign up. It gates customer-based metrics such as CAC and LTV:CAC, whose denominator is new customers (counted once per person via first_time_for_user) rather than every conversion. Defaults to false.'
                    ),
                counts_as_revenue: zod
                    .union([zod.boolean(), zod.null()])
                    .optional()
                    .describe(
                        'Marks this goal as revenue-bearing: the value of a conversion is a monetary amount, not a count or an arbitrary numeric property. It gates revenue metrics such as ROAS and LTV:CAC. The amount itself comes from math_property, and its currency from math_property_revenue_currency, the same shape Revenue analytics uses for revenue events. Independent of counts_as_customer: a purchase is usually both, a trial signup neither. Defaults to false.'
                    ),
                custom_name: zod.union([zod.string(), zod.null()]).optional(),
                distinct_id_field: zod.string(),
                dw_source_type: zod.union([zod.string(), zod.null()]).optional(),
                fixedProperties: zod
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeFixedPropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe(
                        "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                    ),
                id: zod.string(),
                id_field: zod.string(),
                kind: zod
                    .literal('DataWarehouseNode')
                    .default(marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreeKindDefault),
                math: zod
                    .union([
                        zod.enum([
                            'total',
                            'dau',
                            'weekly_active',
                            'monthly_active',
                            'unique_session',
                            'first_time_for_user',
                            'first_matching_event_for_user',
                        ]),
                        zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                        zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                        zod.enum([
                            'avg_count_per_actor',
                            'min_count_per_actor',
                            'max_count_per_actor',
                            'median_count_per_actor',
                            'p75_count_per_actor',
                            'p90_count_per_actor',
                            'p95_count_per_actor',
                            'p99_count_per_actor',
                        ]),
                        zod.enum([
                            'total',
                            'sum',
                            'unique_session',
                            'min',
                            'max',
                            'avg',
                            'dau',
                            'unique_group',
                            'hogql',
                        ]),
                        zod.enum(['total', 'dau']),
                        zod.literal('unique_group'),
                        zod.literal('hogql'),
                        zod.null(),
                    ])
                    .optional(),
                math_group_type_index: zod
                    .union([
                        zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                        zod.null(),
                    ])
                    .optional(),
                math_hogql: zod.union([zod.string(), zod.null()]).optional(),
                math_multiplier: zod.union([zod.number(), zod.null()]).optional(),
                math_property: zod.union([zod.string(), zod.null()]).optional(),
                math_property_revenue_currency: zod
                    .union([
                        zod.object({
                            property: zod.union([zod.string(), zod.null()]).optional(),
                            static: zod
                                .union([
                                    zod.enum([
                                        'AED',
                                        'AFN',
                                        'ALL',
                                        'AMD',
                                        'ANG',
                                        'AOA',
                                        'ARS',
                                        'AUD',
                                        'AWG',
                                        'AZN',
                                        'BAM',
                                        'BBD',
                                        'BDT',
                                        'BGN',
                                        'BHD',
                                        'BIF',
                                        'BMD',
                                        'BND',
                                        'BOB',
                                        'BRL',
                                        'BSD',
                                        'BTC',
                                        'BTN',
                                        'BWP',
                                        'BYN',
                                        'BZD',
                                        'CAD',
                                        'CDF',
                                        'CHF',
                                        'CLP',
                                        'CNY',
                                        'COP',
                                        'CRC',
                                        'CVE',
                                        'CZK',
                                        'DJF',
                                        'DKK',
                                        'DOP',
                                        'DZD',
                                        'EGP',
                                        'ERN',
                                        'ETB',
                                        'EUR',
                                        'FJD',
                                        'GBP',
                                        'GEL',
                                        'GHS',
                                        'GIP',
                                        'GMD',
                                        'GNF',
                                        'GTQ',
                                        'GYD',
                                        'HKD',
                                        'HNL',
                                        'HRK',
                                        'HTG',
                                        'HUF',
                                        'IDR',
                                        'ILS',
                                        'INR',
                                        'IQD',
                                        'IRR',
                                        'ISK',
                                        'JMD',
                                        'JOD',
                                        'JPY',
                                        'KES',
                                        'KGS',
                                        'KHR',
                                        'KMF',
                                        'KRW',
                                        'KWD',
                                        'KYD',
                                        'KZT',
                                        'LAK',
                                        'LBP',
                                        'LKR',
                                        'LRD',
                                        'LTL',
                                        'LVL',
                                        'LSL',
                                        'LYD',
                                        'MAD',
                                        'MDL',
                                        'MGA',
                                        'MKD',
                                        'MMK',
                                        'MNT',
                                        'MOP',
                                        'MRU',
                                        'MTL',
                                        'MUR',
                                        'MVR',
                                        'MWK',
                                        'MXN',
                                        'MYR',
                                        'MZN',
                                        'NAD',
                                        'NGN',
                                        'NIO',
                                        'NOK',
                                        'NPR',
                                        'NZD',
                                        'OMR',
                                        'PAB',
                                        'PEN',
                                        'PGK',
                                        'PHP',
                                        'PKR',
                                        'PLN',
                                        'PYG',
                                        'QAR',
                                        'RON',
                                        'RSD',
                                        'RUB',
                                        'RWF',
                                        'SAR',
                                        'SBD',
                                        'SCR',
                                        'SDG',
                                        'SEK',
                                        'SGD',
                                        'SRD',
                                        'SSP',
                                        'STN',
                                        'SYP',
                                        'SZL',
                                        'THB',
                                        'TJS',
                                        'TMT',
                                        'TND',
                                        'TOP',
                                        'TRY',
                                        'TTD',
                                        'TWD',
                                        'TZS',
                                        'UAH',
                                        'UGX',
                                        'USD',
                                        'UYU',
                                        'UZS',
                                        'VES',
                                        'VND',
                                        'VUV',
                                        'WST',
                                        'XAF',
                                        'XCD',
                                        'XOF',
                                        'XPF',
                                        'YER',
                                        'ZAR',
                                        'ZMW',
                                    ]),
                                    zod.null(),
                                ])
                                .optional(),
                        }),
                        zod.null(),
                    ])
                    .optional(),
                math_property_type: zod.union([zod.string(), zod.null()]).optional(),
                name: zod.union([zod.string(), zod.null()]).optional(),
                optionalInFunnel: zod.union([zod.boolean(), zod.null()]).optional(),
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneOperatorDefault
                                        ),
                                    type: zod
                                        .literal('event')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemThreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemFourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemFiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenKeyDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenOperatorDefault
                                        ),
                                    type: zod
                                        .literal('cohort')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemSevenTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemEightTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemNineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnezeroTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOneoneTypeDefault
                                        )
                                        .describe('Event property with "$feature/\" prepended'),
                                    value: zod
                                        .union([
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnetwoOperatorDefault
                                        )
                                        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
                                    type: zod
                                        .literal('flag')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnetwoTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnethreeTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnefourTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnefiveTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnesixTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnesevenTypeDefault
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
                                    type: zod
                                        .literal('metric_attribute')
                                        .default(
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemOnenineTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwooneTypeDefault
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
                                            marketingAnalyticsConversionGoalsCreateCreateBodyGoalOneThreePropertiesOneItemTwotwoTypeDefault
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
                    .optional()
                    .describe('Properties configurable in the interface'),
                response: zod.union([zod.record(zod.string(), zod.unknown()), zod.null()]).optional(),
                schema_map: zod.record(zod.string(), zod.union([zod.string(), zod.unknown()])),
                table_name: zod.string(),
                timestamp_field: zod.string(),
                version: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('version of the node, used for schema migrations'),
            }),
        ])
        .describe('Wrapper for OpenAPI schema generation - one goal, in any of the three node shapes.')
        .describe(
            'The conversion goal. Must match one of the ConversionGoalFilter shapes: an events node, an actions node or a data warehouse node. On create, conversion_goal_id is assigned by the server and any value sent is ignored. On update, only the fields you send are changed.'
        ),
})

/**
 * Check the platform → data-warehouse side of every native marketing integration: connection state, sync recency, row counts, required-table status, and schema-mapping coverage. Read-only.
 * @summary List marketing data sources
 */
export const MarketingAnalyticsDataSourcesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MarketingAnalyticsDataSourcesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    source_type: zod.string().nullish().describe("Optional. Restrict to one integration (e.g. 'GoogleAds')."),
})

/**
 * Aggregate data-source sync health, UTM attribution health, and conversion-goal config into a single per-integration diagnostic with recommended actions. Read-only.
 * @summary Diagnose marketing analytics
 */
export const MarketingAnalyticsDiagnoseRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysDefault = 7
export const marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysMax = 365

export const marketingAnalyticsDiagnoseRetrieveQueryIncludeConversionGoalsDefault = true

export const MarketingAnalyticsDiagnoseRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribution_lookback_days: zod
        .number()
        .min(1)
        .max(marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysMax)
        .default(marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysDefault)
        .describe('Lookback window for attribution health (1-365 days); defaults to 7'),
    include_conversion_goals: zod
        .boolean()
        .default(marketingAnalyticsDiagnoseRetrieveQueryIncludeConversionGoalsDefault)
        .describe('Whether to include the conversion-goal summary in the diagnostic'),
    source_type: zod.string().nullish().describe('Optional integration filter'),
})

/**
 * Break down a single conversion goal's events over a period by event name, utm_source, and matched integration, with a small sample of events. Read-only.
 * @summary Explain a conversion goal
 */
export const MarketingAnalyticsExplainConversionGoalRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MarketingAnalyticsExplainConversionGoalRetrieveQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.string().nullish().describe('ISO start; defaults to 30 days ago'),
    date_to: zod.string().nullish().describe('ISO end; defaults to now'),
    goal_id: zod.string().min(1).describe('Id of the conversion goal to explain (from list_conversion_goals).'),
})

/**
 * Rank existing custom events as conversion-goal candidates by volume, UTM-tag coverage, and unique users, excluding system/autocaptured events. Read-only.
 * @summary Suggest conversion goals
 */
export const MarketingAnalyticsSuggestConversionGoalsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsSuggestConversionGoalsRetrieveQueryMinCountDefault = 50
export const marketingAnalyticsSuggestConversionGoalsRetrieveQueryTopNDefault = 10

export const MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    min_count: zod
        .number()
        .default(marketingAnalyticsSuggestConversionGoalsRetrieveQueryMinCountDefault)
        .describe('Minimum 30d event count to be a candidate'),
    top_n: zod
        .number()
        .default(marketingAnalyticsSuggestConversionGoalsRetrieveQueryTopNDefault)
        .describe('Max candidates to return'),
})

/**
 * Detect unmatched utm_source values from recent events and propose custom_source_mappings entries, alongside the full utm_source catalogue and current mappings. Read-only.
 * @summary Suggest UTM source mappings
 */
export const MarketingAnalyticsSuggestUtmMappingsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysDefault = 90
export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysMax = 365

export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryMinEventCountDefault = 10

export const MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    lookback_days: zod
        .number()
        .min(1)
        .max(marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysMax)
        .default(marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysDefault)
        .describe('Days of history to inspect (1-365); defaults to 90'),
    min_event_count: zod
        .number()
        .default(marketingAnalyticsSuggestUtmMappingsRetrieveQueryMinEventCountDefault)
        .describe('Only suggest for raw values with >= this many events'),
})

/**
 * Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.
 * @summary Run UTM audit
 */
export const MarketingAnalyticsUtmAuditRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsUtmAuditRetrieveQueryDateFromDefault = `-30d`

export const MarketingAnalyticsUtmAuditRetrieveQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .min(1)
        .default(marketingAnalyticsUtmAuditRetrieveQueryDateFromDefault)
        .describe('Start date for the audit period'),
    date_to: zod.string().nullish().describe('End date for the audit period'),
})
