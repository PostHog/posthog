/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const SubscriptionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SubscriptionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const SubscriptionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const subscriptionsCreateBodyIntervalMin = -2147483648
export const subscriptionsCreateBodyIntervalMax = 2147483647

export const subscriptionsCreateBodyBysetposMin = -2147483648
export const subscriptionsCreateBodyBysetposMax = 2147483647

export const subscriptionsCreateBodyCountMin = -2147483648
export const subscriptionsCreateBodyCountMax = 2147483647

export const subscriptionsCreateBodyTitleMax = 100

export const SubscriptionsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsCreateBodyIntervalMin)
            .max(subscriptionsCreateBodyIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsCreateBodyBysetposMin)
            .max(subscriptionsCreateBodyBysetposMax)
            .nullish(),
        count: zod.number().min(subscriptionsCreateBodyCountMin).max(subscriptionsCreateBodyCountMax).nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsCreateBodyTitleMax).nullish(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const SubscriptionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SubscriptionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this subscription.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const subscriptionsPartialUpdateBodyIntervalMin = -2147483648
export const subscriptionsPartialUpdateBodyIntervalMax = 2147483647

export const subscriptionsPartialUpdateBodyBysetposMin = -2147483648
export const subscriptionsPartialUpdateBodyBysetposMax = 2147483647

export const subscriptionsPartialUpdateBodyCountMin = -2147483648
export const subscriptionsPartialUpdateBodyCountMax = 2147483647

export const subscriptionsPartialUpdateBodyTitleMax = 100

export const SubscriptionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .optional()
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string().optional(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .optional()
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsPartialUpdateBodyIntervalMin)
            .max(subscriptionsPartialUpdateBodyIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateBodyBysetposMin)
            .max(subscriptionsPartialUpdateBodyBysetposMax)
            .nullish(),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateBodyCountMin)
            .max(subscriptionsPartialUpdateBodyCountMax)
            .nullish(),
        start_date: zod.iso.datetime({}).optional(),
        until_date: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsPartialUpdateBodyTitleMax).nullish(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')
