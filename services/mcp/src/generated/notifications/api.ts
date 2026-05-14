/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const NotificationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const NotificationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const NotificationsSendConciergeCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const notificationsSendConciergeCreateBodyTitleMax = 255

export const notificationsSendConciergeCreateBodyPriorityDefault = `normal`
export const notificationsSendConciergeCreateBodyNotificationStyleDefault = `envelope`
export const notificationsSendConciergeCreateBodySkillDefault = ``
export const notificationsSendConciergeCreateBodyLongFormWizardTextDefault = ``

export const NotificationsSendConciergeCreateBody = /* @__PURE__ */ zod.object({
    target_user_ids: zod
        .array(zod.number())
        .min(1)
        .describe(
            'IDs of the PostHog users who should receive this notification. Each user will receive the notification in their current project. Users without a current team are skipped.'
        ),
    title: zod
        .string()
        .max(notificationsSendConciergeCreateBodyTitleMax)
        .describe('Short headline shown to the user in the notification UI (max 255 characters).'),
    body: zod
        .string()
        .describe(
            'Main message body shown beneath the title. Can be left blank if the long-form wizard text carries the message.'
        ),
    priority: zod
        .enum(['normal', 'critical'])
        .describe('* `normal` - NORMAL\n* `critical` - CRITICAL')
        .default(notificationsSendConciergeCreateBodyPriorityDefault)
        .describe(
            "Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast).\n\n* `normal` - NORMAL\n* `critical` - CRITICAL"
        ),
    notification_style: zod
        .enum(['envelope', 'scroll', 'galactic'])
        .describe('* `envelope` - envelope\n* `scroll` - scroll\n* `galactic` - galactic')
        .default(notificationsSendConciergeCreateBodyNotificationStyleDefault)
        .describe(
            "Visual style for the notification: 'envelope', 'scroll', or 'galactic'.\n\n* `envelope` - envelope\n* `scroll` - scroll\n* `galactic` - galactic"
        ),
    skill: zod
        .string()
        .default(notificationsSendConciergeCreateBodySkillDefault)
        .describe('Optional skill identifier used by the wizard UI to render an associated capability for the user.'),
    long_form_wizard_text: zod
        .string()
        .default(notificationsSendConciergeCreateBodyLongFormWizardTextDefault)
        .describe('Optional long-form text shown in the notification wizard expanded view.'),
})
