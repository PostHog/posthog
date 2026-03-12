/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ActivityLogListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ActivityLogListQueryParams = zod.object({
    item_id: zod.string().min(1).optional().describe('Filter by the ID of the affected resource.'),
    scope: zod
        .string()
        .min(1)
        .optional()
        .describe('Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".'),
    scopes: zod
        .string()
        .min(1)
        .optional()
        .describe('Filter by multiple scopes, comma-separated. E.g. "FeatureFlag,Insight".'),
    user: zod.string().optional().describe('Filter by user UUID who performed the action.'),
})

export const activityLogListResponseUserDistinctIdMax = 200

export const activityLogListResponseUserFirstNameMax = 150

export const activityLogListResponseUserLastNameMax = 150

export const activityLogListResponseUserEmailMax = 254

export const activityLogListResponseActivityMax = 79

export const activityLogListResponseItemIdMax = 72

export const activityLogListResponseScopeMax = 79

export const ActivityLogListResponseItem = zod.object({
    id: zod.string(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(activityLogListResponseUserDistinctIdMax).nullish(),
        first_name: zod.string().max(activityLogListResponseUserFirstNameMax).optional(),
        last_name: zod.string().max(activityLogListResponseUserLastNameMax).optional(),
        email: zod.string().email().max(activityLogListResponseUserEmailMax),
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
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    organization_id: zod.string().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    activity: zod.string().max(activityLogListResponseActivityMax),
    item_id: zod.string().max(activityLogListResponseItemIdMax).nullish(),
    scope: zod.string().max(activityLogListResponseScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.string().datetime({}).optional(),
})
export const ActivityLogListResponse = zod.array(ActivityLogListResponseItem)
