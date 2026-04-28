/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const groupsTypesMetricsListPathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsListPathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsListParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsListPathGroupTypeIndexMin)
        .max(groupsTypesMetricsListPathGroupTypeIndexMax),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const GroupsTypesMetricsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const groupsTypesMetricsCreatePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsCreatePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsCreateParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsCreatePathGroupTypeIndexMin)
        .max(groupsTypesMetricsCreatePathGroupTypeIndexMax),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsCreateBodyNameMax = 255

export const groupsTypesMetricsCreateBodyFormatDefault = `numeric`
export const groupsTypesMetricsCreateBodyIntervalDefault = 7
export const groupsTypesMetricsCreateBodyDisplayDefault = `number`
export const groupsTypesMetricsCreateBodyMathDefault = `count`
export const groupsTypesMetricsCreateBodyMathPropertyMax = 255

export const GroupsTypesMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsCreateBodyNameMax)
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .default(groupsTypesMetricsCreateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsCreateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .default(groupsTypesMetricsCreateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'HogQL filter definition used to compute the metric. Same shape as HogFunction filters: a dict containing an `events` list and optional `properties` list.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .default(groupsTypesMetricsCreateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsCreateBodyMathPropertyMax)
        .nullish()
        .describe('Event property to sum. Required when `math` is `sum` and forbidden when `math` is `count`.'),
})

export const groupsTypesMetricsRetrievePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsRetrievePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsRetrieveParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsRetrievePathGroupTypeIndexMin)
        .max(groupsTypesMetricsRetrievePathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsPartialUpdatePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsPartialUpdatePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsPartialUpdateParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsPartialUpdatePathGroupTypeIndexMin)
        .max(groupsTypesMetricsPartialUpdatePathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsPartialUpdateBodyNameMax = 255

export const groupsTypesMetricsPartialUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyNameMax)
        .optional()
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .optional()
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .optional()
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .optional()
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'HogQL filter definition used to compute the metric. Same shape as HogFunction filters: a dict containing an `events` list and optional `properties` list.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .optional()
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyMathPropertyMax)
        .nullish()
        .describe('Event property to sum. Required when `math` is `sum` and forbidden when `math` is `count`.'),
})

export const groupsTypesMetricsDestroyPathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsDestroyPathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsDestroyParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsDestroyPathGroupTypeIndexMin)
        .max(groupsTypesMetricsDestroyPathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
