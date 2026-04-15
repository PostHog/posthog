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
