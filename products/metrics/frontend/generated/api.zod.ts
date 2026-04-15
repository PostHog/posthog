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
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const EventFilterMetricsRetrieveResponse = /* @__PURE__ */ zod.object({
    labels: zod.array(zod.string()),
    series: zod.array(
        zod.object({
            name: zod.string(),
            values: zod.array(zod.number()),
        })
    ),
})

/**
 * Single event filter per team.
GET  /event_filter/ — returns the config (or null if not yet created)
POST /event_filter/ — creates or updates the config (upsert)
GET  /event_filter/metrics/ — time-series metrics
GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const EventFilterMetricsTotalsRetrieveResponse = /* @__PURE__ */ zod.object({
    totals: zod.record(zod.string(), zod.number()),
})

export const groupsTypesMetricsListResponseResultsItemNameMax = 255

export const groupsTypesMetricsListResponseResultsItemIntervalMin = -2147483648
export const groupsTypesMetricsListResponseResultsItemIntervalMax = 2147483647

export const GroupsTypesMetricsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(groupsTypesMetricsListResponseResultsItemNameMax),
            format: zod
                .enum(['numeric', 'currency'])
                .optional()
                .describe('* `numeric` - numeric\n* `currency` - currency'),
            interval: zod
                .number()
                .min(groupsTypesMetricsListResponseResultsItemIntervalMin)
                .max(groupsTypesMetricsListResponseResultsItemIntervalMax)
                .optional()
                .describe('In days'),
            display: zod
                .enum(['number', 'sparkline'])
                .optional()
                .describe('* `number` - number\n* `sparkline` - sparkline'),
            filters: zod.unknown(),
        })
    ),
})

export const groupsTypesMetricsCreateBodyNameMax = 255

export const groupsTypesMetricsCreateBodyIntervalMin = -2147483648
export const groupsTypesMetricsCreateBodyIntervalMax = 2147483647

export const GroupsTypesMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsCreateBodyNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsCreateBodyIntervalMin)
        .max(groupsTypesMetricsCreateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
})

export const groupsTypesMetricsRetrieveResponseNameMax = 255

export const groupsTypesMetricsRetrieveResponseIntervalMin = -2147483648
export const groupsTypesMetricsRetrieveResponseIntervalMax = 2147483647

export const GroupsTypesMetricsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(groupsTypesMetricsRetrieveResponseNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsRetrieveResponseIntervalMin)
        .max(groupsTypesMetricsRetrieveResponseIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
})

export const groupsTypesMetricsUpdateBodyNameMax = 255

export const groupsTypesMetricsUpdateBodyIntervalMin = -2147483648
export const groupsTypesMetricsUpdateBodyIntervalMax = 2147483647

export const GroupsTypesMetricsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsUpdateBodyNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsUpdateBodyIntervalMin)
        .max(groupsTypesMetricsUpdateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
})

export const groupsTypesMetricsUpdateResponseNameMax = 255

export const groupsTypesMetricsUpdateResponseIntervalMin = -2147483648
export const groupsTypesMetricsUpdateResponseIntervalMax = 2147483647

export const GroupsTypesMetricsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(groupsTypesMetricsUpdateResponseNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsUpdateResponseIntervalMin)
        .max(groupsTypesMetricsUpdateResponseIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
})

export const groupsTypesMetricsPartialUpdateBodyNameMax = 255

export const groupsTypesMetricsPartialUpdateBodyIntervalMin = -2147483648
export const groupsTypesMetricsPartialUpdateBodyIntervalMax = 2147483647

export const GroupsTypesMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsPartialUpdateBodyNameMax).optional(),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsPartialUpdateBodyIntervalMin)
        .max(groupsTypesMetricsPartialUpdateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown().optional(),
})

export const groupsTypesMetricsPartialUpdateResponseNameMax = 255

export const groupsTypesMetricsPartialUpdateResponseIntervalMin = -2147483648
export const groupsTypesMetricsPartialUpdateResponseIntervalMax = 2147483647

export const GroupsTypesMetricsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(groupsTypesMetricsPartialUpdateResponseNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsPartialUpdateResponseIntervalMin)
        .max(groupsTypesMetricsPartialUpdateResponseIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
})
