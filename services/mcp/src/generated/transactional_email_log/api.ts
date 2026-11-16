/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the project's transactional email sends, newest first. The log keeps sends for 30 days.
 * @summary List transactional email sends
 */
export const TransactionalEmailLogListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const transactionalEmailLogListQueryLimitDefault = 50
export const transactionalEmailLogListQueryLimitMax = 200

export const transactionalEmailLogListQueryOffsetDefault = 0
export const transactionalEmailLogListQueryOffsetMin = 0

export const TransactionalEmailLogListQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued before this time. Defaults to now.'),
    limit: zod
        .number()
        .min(1)
        .max(transactionalEmailLogListQueryLimitMax)
        .default(transactionalEmailLogListQueryLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(transactionalEmailLogListQueryOffsetMin)
        .default(transactionalEmailLogListQueryOffsetDefault)
        .describe('Sends to skip.'),
    search: zod
        .string()
        .optional()
        .describe("A `message_id` for an exact match, or part of the recipient's email address."),
    status: zod
        .enum(['queued', 'failed', 'sent', 'delivered', 'bounced', 'complained'])
        .optional()
        .describe(
            'Only sends in this delivery status.\n\n\* `queued` - Queued\n\* `failed` - Failed\n\* `sent` - Sent\n\* `delivered` - Delivered\n\* `bounced` - Bounced\n\* `complained` - Complained'
        ),
    workflow_id: zod.string().optional().describe('Only sends of the transactional email backed by this workflow.'),
})

/**
 * Get one send with its timeline: when it was queued, sent, delivered, opened and clicked.
 * @summary Get a transactional email send
 */
export const TransactionalEmailLogRetrieveParams = () => zod.object({
    id: zod.string().describe('The `message_id` that the send returned.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Of the people a transactional email was sent to, count those who did an event within a window after their first send, and add up the revenue on those events.
 * @summary Get what happened after a transactional email
 */
export const TransactionalEmailLogResultsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const transactionalEmailLogResultsRetrieveQueryWindowDaysDefault = 7
export const transactionalEmailLogResultsRetrieveQueryWindowDaysMax = 30

export const TransactionalEmailLogResultsRetrieveQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued before this time. Defaults to now.'),
    event: zod.string().min(1).describe('The event that counts as a conversion, such as `signed_up`.'),
    revenue_property: zod.string().optional().describe('An event property holding a revenue amount to add up.'),
    window_days: zod
        .number()
        .min(1)
        .max(transactionalEmailLogResultsRetrieveQueryWindowDaysMax)
        .default(transactionalEmailLogResultsRetrieveQueryWindowDaysDefault)
        .describe('How many days after the first send the event still counts.'),
    workflow_id: zod.string().describe('The workflow behind the transactional email.'),
})

/**
 * Count sends by delivery status, opens and clicks, per template or per sending domain.
 * @summary Get transactional email delivery stats
 */
export const TransactionalEmailLogStatsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const transactionalEmailLogStatsRetrieveQueryGroupByDefault = `template`

export const TransactionalEmailLogStatsRetrieveQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued at or after this time. Defaults to 7 days ago. The log keeps sends for 30 days.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends queued before this time. Defaults to now.'),
    group_by: zod
        .enum(['template', 'sending_domain'])
        .default(transactionalEmailLogStatsRetrieveQueryGroupByDefault)
        .describe(
            'Count per template or per sending domain.\n\n\* `template` - Template\n\* `sending_domain` - Sending domain'
        ),
})
