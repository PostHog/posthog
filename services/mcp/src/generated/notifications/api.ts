/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const NotificationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const notificationsListQueryLimitMax = 100

export const NotificationsListQueryParams = () => zod.object({
    archived: zod
        .boolean()
        .optional()
        .describe(
            'When true, return only notifications the recipient has archived; otherwise return only non-archived notifications (the default)'
        ),
    created_after: zod.string().optional().describe('ISO 8601 timestamp; only events at or after this time'),
    created_before: zod.string().optional().describe('ISO 8601 timestamp; only events strictly before this time'),
    limit: zod
        .number()
        .max(notificationsListQueryLimitMax)
        .optional()
        .describe('Number of results to return per page.'),
    notification_type: zod.string().optional().describe('Filter by notification type'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    read: zod.boolean().optional().describe('Filter by whether the recipient has read the notification'),
    resource_id: zod.string().optional().describe('Filter by the ID of the resource the notification refers to'),
    resource_type: zod
        .string()
        .optional()
        .describe('Filter by the type of the resource the notification refers to (e.g. `insight`, `dashboard`)'),
    target_id: zod.string().optional().describe('Filter by recipient target ID (e.g. a user ID)'),
    target_type: zod.string().optional().describe('Filter by recipient target type (e.g. `user`, `team`)'),
})

export const NotificationsMarkReadBulkCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const notificationsMarkReadBulkCreateBodyNotificationIdsMax = 500

export const NotificationsMarkReadBulkCreateBody = () => zod.object({
    notification_ids: zod
        .array(zod.string())
        .max(notificationsMarkReadBulkCreateBodyNotificationIdsMax)
        .describe(
            'UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.'
        ),
})
