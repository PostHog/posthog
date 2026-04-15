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
 * Explain a log entry using AI.

POST /api/environments/:id/logs/explainLogWithAI/
 */
export const logsExplainLogWithAICreateBodyForceRefreshDefault = false

export const LogsExplainLogWithAICreateBody = /* @__PURE__ */ zod.object({
    uuid: zod.string().describe('UUID of the log entry to explain'),
    timestamp: zod.iso.datetime({}).describe('Timestamp of the log entry (used for efficient lookup)'),
    force_refresh: zod
        .boolean()
        .default(logsExplainLogWithAICreateBodyForceRefreshDefault)
        .describe('Force regenerate explanation, bypassing cache'),
})

export const logsViewsListResponseResultsItemNameMax = 400

export const logsViewsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const logsViewsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const logsViewsListResponseResultsItemCreatedByOneLastNameMax = 150

export const logsViewsListResponseResultsItemCreatedByOneEmailMax = 254

export const LogsViewsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            short_id: zod.string(),
            name: zod.string().max(logsViewsListResponseResultsItemNameMax),
            filters: zod
                .record(zod.string(), zod.unknown())
                .optional()
                .describe(
                    'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
                ),
            pinned: zod.boolean().optional(),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(logsViewsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(logsViewsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(logsViewsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(logsViewsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const logsViewsCreateBodyNameMax = 400

export const LogsViewsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsCreateBodyNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsViewsRetrieveResponseNameMax = 400

export const logsViewsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const logsViewsRetrieveResponseCreatedByOneFirstNameMax = 150

export const logsViewsRetrieveResponseCreatedByOneLastNameMax = 150

export const logsViewsRetrieveResponseCreatedByOneEmailMax = 254

export const LogsViewsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(logsViewsRetrieveResponseNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsViewsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsViewsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsViewsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsViewsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const logsViewsUpdateBodyNameMax = 400

export const LogsViewsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsUpdateBodyNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsViewsUpdateResponseNameMax = 400

export const logsViewsUpdateResponseCreatedByOneDistinctIdMax = 200

export const logsViewsUpdateResponseCreatedByOneFirstNameMax = 150

export const logsViewsUpdateResponseCreatedByOneLastNameMax = 150

export const logsViewsUpdateResponseCreatedByOneEmailMax = 254

export const LogsViewsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(logsViewsUpdateResponseNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsViewsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsViewsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsViewsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsViewsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const logsViewsPartialUpdateBodyNameMax = 400

export const LogsViewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsPartialUpdateBodyNameMax).optional(),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsViewsPartialUpdateResponseNameMax = 400

export const logsViewsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const logsViewsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const logsViewsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const logsViewsPartialUpdateResponseCreatedByOneEmailMax = 254

export const LogsViewsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(logsViewsPartialUpdateResponseNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsViewsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsViewsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsViewsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsViewsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const logsAlertsListResponseResultsItemNameMax = 255

export const logsAlertsListResponseResultsItemThresholdCountMax = 2147483647

export const logsAlertsListResponseResultsItemThresholdOperatorDefault = `above`
export const logsAlertsListResponseResultsItemWindowMinutesMin = 0
export const logsAlertsListResponseResultsItemWindowMinutesMax = 2147483647

export const logsAlertsListResponseResultsItemEvaluationPeriodsDefault = 1
export const logsAlertsListResponseResultsItemEvaluationPeriodsMax = 10

export const logsAlertsListResponseResultsItemDatapointsToAlarmDefault = 1
export const logsAlertsListResponseResultsItemDatapointsToAlarmMax = 10

export const logsAlertsListResponseResultsItemCooldownMinutesMin = 0
export const logsAlertsListResponseResultsItemCooldownMinutesMax = 2147483647

export const logsAlertsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const logsAlertsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const logsAlertsListResponseResultsItemCreatedByOneLastNameMax = 150

export const logsAlertsListResponseResultsItemCreatedByOneEmailMax = 254

export const LogsAlertsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(logsAlertsListResponseResultsItemNameMax),
            enabled: zod.boolean().optional(),
            filters: zod
                .unknown()
                .describe(
                    'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
                ),
            threshold_count: zod.number().min(1).max(logsAlertsListResponseResultsItemThresholdCountMax),
            threshold_operator: zod
                .enum(['above', 'below'])
                .describe('* `above` - Above\n* `below` - Below')
                .default(logsAlertsListResponseResultsItemThresholdOperatorDefault)
                .describe(
                    'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
                ),
            window_minutes: zod
                .number()
                .min(logsAlertsListResponseResultsItemWindowMinutesMin)
                .max(logsAlertsListResponseResultsItemWindowMinutesMax)
                .optional(),
            check_interval_minutes: zod.number(),
            state: zod
                .enum(['not_firing', 'firing', 'pending_resolve', 'errored', 'snoozed'])
                .describe(
                    '* `not_firing` - Not firing\n* `firing` - Firing\n* `pending_resolve` - Pending resolve\n* `errored` - Errored\n* `snoozed` - Snoozed'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(logsAlertsListResponseResultsItemEvaluationPeriodsMax)
                .default(logsAlertsListResponseResultsItemEvaluationPeriodsDefault)
                .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(logsAlertsListResponseResultsItemDatapointsToAlarmMax)
                .default(logsAlertsListResponseResultsItemDatapointsToAlarmDefault)
                .describe(
                    'How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'
                ),
            cooldown_minutes: zod
                .number()
                .min(logsAlertsListResponseResultsItemCooldownMinutesMin)
                .max(logsAlertsListResponseResultsItemCooldownMinutesMax)
                .optional(),
            snooze_until: zod.iso.datetime({}).nullish(),
            next_check_at: zod.iso.datetime({}).nullable(),
            last_notified_at: zod.iso.datetime({}).nullable(),
            last_checked_at: zod.iso.datetime({}).nullable(),
            consecutive_failures: zod.number(),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(logsAlertsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(logsAlertsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(logsAlertsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(logsAlertsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const logsAlertsCreateBodyNameMax = 255

export const logsAlertsCreateBodyThresholdCountMax = 2147483647

export const logsAlertsCreateBodyThresholdOperatorDefault = `above`
export const logsAlertsCreateBodyWindowMinutesMin = 0
export const logsAlertsCreateBodyWindowMinutesMax = 2147483647

export const logsAlertsCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsCreateBodyCooldownMinutesMin = 0
export const logsAlertsCreateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsCreateBodyNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsCreateBodyThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsCreateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsCreateBodyWindowMinutesMin)
        .max(logsAlertsCreateBodyWindowMinutesMax)
        .optional(),
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
        .max(logsAlertsCreateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
})

export const logsAlertsRetrieveResponseNameMax = 255

export const logsAlertsRetrieveResponseThresholdCountMax = 2147483647

export const logsAlertsRetrieveResponseThresholdOperatorDefault = `above`
export const logsAlertsRetrieveResponseWindowMinutesMin = 0
export const logsAlertsRetrieveResponseWindowMinutesMax = 2147483647

export const logsAlertsRetrieveResponseEvaluationPeriodsDefault = 1
export const logsAlertsRetrieveResponseEvaluationPeriodsMax = 10

export const logsAlertsRetrieveResponseDatapointsToAlarmDefault = 1
export const logsAlertsRetrieveResponseDatapointsToAlarmMax = 10

export const logsAlertsRetrieveResponseCooldownMinutesMin = 0
export const logsAlertsRetrieveResponseCooldownMinutesMax = 2147483647

export const logsAlertsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const logsAlertsRetrieveResponseCreatedByOneFirstNameMax = 150

export const logsAlertsRetrieveResponseCreatedByOneLastNameMax = 150

export const logsAlertsRetrieveResponseCreatedByOneEmailMax = 254

export const LogsAlertsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(logsAlertsRetrieveResponseNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsRetrieveResponseThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsRetrieveResponseThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsRetrieveResponseWindowMinutesMin)
        .max(logsAlertsRetrieveResponseWindowMinutesMax)
        .optional(),
    check_interval_minutes: zod.number(),
    state: zod
        .enum(['not_firing', 'firing', 'pending_resolve', 'errored', 'snoozed'])
        .describe(
            '* `not_firing` - Not firing\n* `firing` - Firing\n* `pending_resolve` - Pending resolve\n* `errored` - Errored\n* `snoozed` - Snoozed'
        ),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsRetrieveResponseEvaluationPeriodsMax)
        .default(logsAlertsRetrieveResponseEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsRetrieveResponseDatapointsToAlarmMax)
        .default(logsAlertsRetrieveResponseDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsRetrieveResponseCooldownMinutesMin)
        .max(logsAlertsRetrieveResponseCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
    next_check_at: zod.iso.datetime({}).nullable(),
    last_notified_at: zod.iso.datetime({}).nullable(),
    last_checked_at: zod.iso.datetime({}).nullable(),
    consecutive_failures: zod.number(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsAlertsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsAlertsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsAlertsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsAlertsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const logsAlertsUpdateBodyNameMax = 255

export const logsAlertsUpdateBodyThresholdCountMax = 2147483647

export const logsAlertsUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsUpdateBodyWindowMinutesMin = 0
export const logsAlertsUpdateBodyWindowMinutesMax = 2147483647

export const logsAlertsUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsUpdateBodyCooldownMinutesMin = 0
export const logsAlertsUpdateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsUpdateBodyNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsUpdateBodyThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsUpdateBodyWindowMinutesMin)
        .max(logsAlertsUpdateBodyWindowMinutesMax)
        .optional(),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateBodyEvaluationPeriodsMax)
        .default(logsAlertsUpdateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateBodyDatapointsToAlarmMax)
        .default(logsAlertsUpdateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsUpdateBodyCooldownMinutesMin)
        .max(logsAlertsUpdateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
})

export const logsAlertsUpdateResponseNameMax = 255

export const logsAlertsUpdateResponseThresholdCountMax = 2147483647

export const logsAlertsUpdateResponseThresholdOperatorDefault = `above`
export const logsAlertsUpdateResponseWindowMinutesMin = 0
export const logsAlertsUpdateResponseWindowMinutesMax = 2147483647

export const logsAlertsUpdateResponseEvaluationPeriodsDefault = 1
export const logsAlertsUpdateResponseEvaluationPeriodsMax = 10

export const logsAlertsUpdateResponseDatapointsToAlarmDefault = 1
export const logsAlertsUpdateResponseDatapointsToAlarmMax = 10

export const logsAlertsUpdateResponseCooldownMinutesMin = 0
export const logsAlertsUpdateResponseCooldownMinutesMax = 2147483647

export const logsAlertsUpdateResponseCreatedByOneDistinctIdMax = 200

export const logsAlertsUpdateResponseCreatedByOneFirstNameMax = 150

export const logsAlertsUpdateResponseCreatedByOneLastNameMax = 150

export const logsAlertsUpdateResponseCreatedByOneEmailMax = 254

export const LogsAlertsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(logsAlertsUpdateResponseNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsUpdateResponseThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsUpdateResponseThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsUpdateResponseWindowMinutesMin)
        .max(logsAlertsUpdateResponseWindowMinutesMax)
        .optional(),
    check_interval_minutes: zod.number(),
    state: zod
        .enum(['not_firing', 'firing', 'pending_resolve', 'errored', 'snoozed'])
        .describe(
            '* `not_firing` - Not firing\n* `firing` - Firing\n* `pending_resolve` - Pending resolve\n* `errored` - Errored\n* `snoozed` - Snoozed'
        ),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateResponseEvaluationPeriodsMax)
        .default(logsAlertsUpdateResponseEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateResponseDatapointsToAlarmMax)
        .default(logsAlertsUpdateResponseDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsUpdateResponseCooldownMinutesMin)
        .max(logsAlertsUpdateResponseCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
    next_check_at: zod.iso.datetime({}).nullable(),
    last_notified_at: zod.iso.datetime({}).nullable(),
    last_checked_at: zod.iso.datetime({}).nullable(),
    consecutive_failures: zod.number(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsAlertsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsAlertsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsAlertsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsAlertsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

export const logsAlertsPartialUpdateBodyNameMax = 255

export const logsAlertsPartialUpdateBodyThresholdCountMax = 2147483647

export const logsAlertsPartialUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsPartialUpdateBodyWindowMinutesMin = 0
export const logsAlertsPartialUpdateBodyWindowMinutesMax = 2147483647

export const logsAlertsPartialUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsPartialUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsPartialUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsPartialUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsPartialUpdateBodyCooldownMinutesMin = 0
export const logsAlertsPartialUpdateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsPartialUpdateBodyNameMax).optional(),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsPartialUpdateBodyThresholdCountMax).optional(),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsPartialUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateBodyWindowMinutesMin)
        .max(logsAlertsPartialUpdateBodyWindowMinutesMax)
        .optional(),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyEvaluationPeriodsMax)
        .default(logsAlertsPartialUpdateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyDatapointsToAlarmMax)
        .default(logsAlertsPartialUpdateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateBodyCooldownMinutesMin)
        .max(logsAlertsPartialUpdateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
})

export const logsAlertsPartialUpdateResponseNameMax = 255

export const logsAlertsPartialUpdateResponseThresholdCountMax = 2147483647

export const logsAlertsPartialUpdateResponseThresholdOperatorDefault = `above`
export const logsAlertsPartialUpdateResponseWindowMinutesMin = 0
export const logsAlertsPartialUpdateResponseWindowMinutesMax = 2147483647

export const logsAlertsPartialUpdateResponseEvaluationPeriodsDefault = 1
export const logsAlertsPartialUpdateResponseEvaluationPeriodsMax = 10

export const logsAlertsPartialUpdateResponseDatapointsToAlarmDefault = 1
export const logsAlertsPartialUpdateResponseDatapointsToAlarmMax = 10

export const logsAlertsPartialUpdateResponseCooldownMinutesMin = 0
export const logsAlertsPartialUpdateResponseCooldownMinutesMax = 2147483647

export const logsAlertsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const logsAlertsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const logsAlertsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const logsAlertsPartialUpdateResponseCreatedByOneEmailMax = 254

export const LogsAlertsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(logsAlertsPartialUpdateResponseNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsPartialUpdateResponseThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsPartialUpdateResponseThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateResponseWindowMinutesMin)
        .max(logsAlertsPartialUpdateResponseWindowMinutesMax)
        .optional(),
    check_interval_minutes: zod.number(),
    state: zod
        .enum(['not_firing', 'firing', 'pending_resolve', 'errored', 'snoozed'])
        .describe(
            '* `not_firing` - Not firing\n* `firing` - Firing\n* `pending_resolve` - Pending resolve\n* `errored` - Errored\n* `snoozed` - Snoozed'
        ),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateResponseEvaluationPeriodsMax)
        .default(logsAlertsPartialUpdateResponseEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateResponseDatapointsToAlarmMax)
        .default(logsAlertsPartialUpdateResponseDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateResponseCooldownMinutesMin)
        .max(logsAlertsPartialUpdateResponseCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
    next_check_at: zod.iso.datetime({}).nullable(),
    last_notified_at: zod.iso.datetime({}).nullable(),
    last_checked_at: zod.iso.datetime({}).nullable(),
    consecutive_failures: zod.number(),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(logsAlertsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(logsAlertsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(logsAlertsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(logsAlertsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}).nullable(),
})

/**
 * Simulate a logs alert on historical data using the full state machine. Read-only — no alert check records are created.
 */

export const logsAlertsSimulateCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsSimulateCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsSimulateCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsSimulateCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsSimulateCreateBodyCooldownMinutesDefault = 0
export const logsAlertsSimulateCreateBodyCooldownMinutesMin = 0

export const LogsAlertsSimulateCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().describe('Filter criteria — same format as LogsAlertConfiguration.filters.'),
    threshold_count: zod.number().min(1).describe('Threshold count to evaluate against.'),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod.number().describe('Window size in minutes — determines bucket interval.'),
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

export const LogsAlertsSimulateCreateResponse = /* @__PURE__ */ zod.object({
    buckets: zod
        .array(
            zod.object({
                timestamp: zod.iso.datetime({}).describe('Bucket start timestamp.'),
                count: zod.number().describe('Number of matching logs in this bucket.'),
                threshold_breached: zod.boolean().describe('Whether the count crossed the threshold in this bucket.'),
                state: zod.string().describe('Alert state after evaluating this bucket.'),
                notification: zod.string().describe('Notification action: none, fire, or resolve.'),
                reason: zod.string().describe('Human-readable explanation of the state transition.'),
            })
        )
        .describe('Time-bucketed counts with full state machine evaluation.'),
    fire_count: zod.number().describe('Number of times the alert would have sent a fire notification.'),
    resolve_count: zod.number().describe('Number of times the alert would have sent a resolve notification.'),
    total_buckets: zod.number().describe('Total number of buckets in the simulation window.'),
    threshold_count: zod.number().describe('Threshold count used for evaluation.'),
    threshold_operator: zod.string().describe('Threshold operator used for evaluation.'),
})

export const logsQueryCreateBodyQueryOneSeverityLevelsDefault = []
export const logsQueryCreateBodyQueryOneServiceNamesDefault = []
export const logsQueryCreateBodyQueryOneFilterGroupDefault = []
export const logsQueryCreateBodyQueryOneLimitDefault = 100

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
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
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
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
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
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(logsQueryCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            limit: zod.number().default(logsQueryCreateBodyQueryOneLimitDefault).describe('Max results (1-1000).'),
            after: zod.string().optional().describe('Pagination cursor from previous response.'),
        })
        .describe('The logs query to execute.'),
})

export const PluginConfigsLogsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            team_id: zod.number(),
            plugin_id: zod.number(),
            plugin_config_id: zod.number(),
            timestamp: zod.iso.datetime({}),
            source: zod
                .enum(['SYSTEM', 'PLUGIN', 'CONSOLE'])
                .describe('* `SYSTEM` - SYSTEM\n* `PLUGIN` - PLUGIN\n* `CONSOLE` - CONSOLE'),
            type: zod
                .enum(['DEBUG', 'LOG', 'INFO', 'WARN', 'ERROR'])
                .describe('* `DEBUG` - DEBUG\n* `LOG` - LOG\n* `INFO` - INFO\n* `WARN` - WARN\n* `ERROR` - ERROR'),
            message: zod.string(),
            instance_id: zod.uuid(),
        })
    ),
})
