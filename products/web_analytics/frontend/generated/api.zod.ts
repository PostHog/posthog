/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Returns an AI summary of the team's web analytics for the supplied filter spec. If a fresh summary is cached it is returned as-is. Otherwise, when check=true the call returns HTTP 204 without invoking the LLM; when check is omitted/false the LLM is invoked, the result is cached, and returned. The generate path is rate-limited per user.
 * @summary Generate AI summary of web analytics
 */
export const webAnalyticsAiSummaryBodyCompareDefault = true
export const webAnalyticsAiSummaryBodyPropertiesItemOperatorDefault = `exact`
export const webAnalyticsAiSummaryBodyPropertiesItemTypeDefault = `event`
export const webAnalyticsAiSummaryBodyFilterTestAccountsDefault = true
export const webAnalyticsAiSummaryBodyDoPathCleaningDefault = false

export const WebAnalyticsAiSummaryBody = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .describe("Start of the analysis window. Accepts a relative spec like '-7d' or an ISO date like '2026-01-01'."),
    date_to: zod
        .string()
        .nullish()
        .describe(
            'End of the analysis window. Accepts the same formats as date_from, or null for an open-ended range up to now.'
        ),
    compare: zod
        .boolean()
        .default(webAnalyticsAiSummaryBodyCompareDefault)
        .describe(
            'When true, include period-over-period change for each metric against the prior equal-length period.'
        ),
    properties: zod
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
                        'Value of your filter. For example `test@example.com` or `https:\/\/example.com\/test\/`. Can be an array for an OR query, like `[\"test@example.com\",\"ok@example.com\"]`'
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
                                '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set\n\* `is_date_exact` - is_date_exact\n\* `is_date_after` - is_date_after\n\* `is_date_before` - is_date_before\n\* `in` - in\n\* `not_in` - not_in'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .default(webAnalyticsAiSummaryBodyPropertiesItemOperatorDefault),
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
                                '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
                            ),
                        zod.enum(['']),
                    ])
                    .default(webAnalyticsAiSummaryBodyPropertiesItemTypeDefault),
            })
        )
        .optional()
        .describe('Property filters applied to all underlying queries.'),
    conversion_goal: zod
        .object({
            actionId: zod.number().optional().describe('ID of the action used as conversion goal.'),
            customEventName: zod.string().optional().describe('Custom event name used as conversion goal.'),
        })
        .nullish()
        .describe(
            'Optional conversion goal — either ActionConversionGoal ({actionId}) or CustomEventConversionGoal ({customEventName}).'
        ),
    filter_test_accounts: zod
        .boolean()
        .default(webAnalyticsAiSummaryBodyFilterTestAccountsDefault)
        .describe('Whether to exclude internal\/test-account events from the analysis.'),
    do_path_cleaning: zod
        .boolean()
        .default(webAnalyticsAiSummaryBodyDoPathCleaningDefault)
        .describe("When true, apply the team's path-cleaning rules before bucketing by page path."),
})

export const webAnalyticsFilterPresetsCreateBodyNameMax = 400

export const WebAnalyticsFilterPresetsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsCreateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsUpdateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsPartialUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const savedCreateBodyNameMax = 400

export const savedCreateBodyUrlMax = 2000

export const savedCreateBodyDataUrlMax = 2000

export const SavedCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedCreateBodyNameMax).nullish(),
    url: zod.url().max(savedCreateBodyUrlMax),
    data_url: zod.url().max(savedCreateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})

export const savedPartialUpdateBodyNameMax = 400

export const savedPartialUpdateBodyUrlMax = 2000

export const savedPartialUpdateBodyDataUrlMax = 2000

export const SavedPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedPartialUpdateBodyNameMax).nullish(),
    url: zod.url().max(savedPartialUpdateBodyUrlMax).optional(),
    data_url: zod.url().max(savedPartialUpdateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})

export const savedRegenerateCreateBodyNameMax = 400

export const savedRegenerateCreateBodyUrlMax = 2000

export const savedRegenerateCreateBodyDataUrlMax = 2000

export const SavedRegenerateCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedRegenerateCreateBodyNameMax).nullish(),
    url: zod.url().max(savedRegenerateCreateBodyUrlMax),
    data_url: zod.url().max(savedRegenerateCreateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})
