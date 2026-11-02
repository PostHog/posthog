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
 * List the signed-in user's tickets with the PostHog support team, newest first, from every channel the user verified: in-app, API, email and Slack. Use it to check whether support has replied.
 * @summary List your PostHog support tickets
 */
export const PosthogSupportTicketsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const posthogSupportTicketsListQueryLimitDefault = 20
export const posthogSupportTicketsListQueryLimitMax = 100

export const posthogSupportTicketsListQueryOffsetDefault = 0
export const posthogSupportTicketsListQueryOffsetMin = 0

export const PosthogSupportTicketsListQueryParams = () => zod.object({
    limit: zod
        .number()
        .min(1)
        .max(posthogSupportTicketsListQueryLimitMax)
        .default(posthogSupportTicketsListQueryLimitDefault)
        .describe('Number of tickets to return.'),
    offset: zod
        .number()
        .min(posthogSupportTicketsListQueryOffsetMin)
        .default(posthogSupportTicketsListQueryOffsetDefault)
        .describe('Number of tickets to skip.'),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            'Only return tickets with this status.\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        ),
})

/**
 * Open a support ticket with the PostHog support team as the signed-in user. The ticket is verified as sent by this user and is about the project in the URL. Search the docs first: only open a ticket when the docs and the project's own data do not answer the question.
 * @summary Open a ticket with PostHog support
 */
export const PosthogSupportTicketsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const posthogSupportTicketsCreateBodySubjectMax = 200

export const posthogSupportTicketsCreateBodyDescriptionMax = 4000

export const posthogSupportTicketsCreateBodyExpectedMax = 1000

export const posthogSupportTicketsCreateBodyActualMax = 1000

export const posthogSupportTicketsCreateBodyAlreadyTriedMax = 1000

export const posthogSupportTicketsCreateBodyDeletionQueryMax = 4000

export const posthogSupportTicketsCreateBodyExpectedEventCountMin = 0

export const posthogSupportTicketsCreateBodyDeletionConsentDefault = false

export const PosthogSupportTicketsCreateBody = () => zod.object({
    request_type: zod
        .enum(['question', 'bug', 'data_deletion', 'billing', 'other'])
        .describe(
            '\* `question` - Question\n\* `bug` - Bug\n\* `data_deletion` - Data deletion\n\* `billing` - Billing\n\* `other` - Other'
        )
        .describe(
            'What kind of help this is. Use `data_deletion` only to ask PostHog staff to permanently delete events, and fill `deletion_query`, `expected_event_count` and `deletion_consent`.\n\n\* `question` - Question\n\* `bug` - Bug\n\* `data_deletion` - Data deletion\n\* `billing` - Billing\n\* `other` - Other'
        ),
    subject: zod
        .string()
        .max(posthogSupportTicketsCreateBodySubjectMax)
        .describe('One line that says what the problem or question is.'),
    description: zod
        .string()
        .max(posthogSupportTicketsCreateBodyDescriptionMax)
        .describe(
            'The full problem or question in plain text. Include event names, flag keys, SDK names and versions, and links to the PostHog pages involved. Do not include secrets, API keys or personal data.'
        ),
    expected: zod
        .string()
        .max(posthogSupportTicketsCreateBodyExpectedMax)
        .optional()
        .describe('What you expected to happen.'),
    actual: zod
        .string()
        .max(posthogSupportTicketsCreateBodyActualMax)
        .optional()
        .describe('What happened instead, with exact error messages.'),
    already_tried: zod
        .string()
        .max(posthogSupportTicketsCreateBodyAlreadyTriedMax)
        .optional()
        .describe('Docs pages read and steps already tried, so support does not repeat them.'),
    deletion_query: zod
        .string()
        .max(posthogSupportTicketsCreateBodyDeletionQueryMax)
        .optional()
        .describe(
            'For `data_deletion` only: a HogQL query with a time range that selects exactly the events to delete. Sent as raw text, so paste it unchanged.'
        ),
    expected_event_count: zod
        .number()
        .min(posthogSupportTicketsCreateBodyExpectedEventCountMin)
        .optional()
        .describe('For `data_deletion` only: the number of events the deletion query returns now.'),
    deletion_consent: zod
        .boolean()
        .default(posthogSupportTicketsCreateBodyDeletionConsentDefault)
        .describe(
            'For `data_deletion` only: true confirms that the user wants these events permanently deleted. Ask the user before you set it. Deleted events cannot be restored.'
        ),
})

/**
 * Read the status and the messages of one of the signed-in user's tickets with PostHog support. Internal notes of the support team are not included.
 * @summary Read a PostHog support ticket
 */
export const posthogSupportTicketsRetrievePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const PosthogSupportTicketsRetrieveParams = () => zod.object({
    id: zod.string().regex(posthogSupportTicketsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const PosthogSupportTicketsRetrieveQueryParams = () => zod.object({
    after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Only return messages sent after this time. When `has_more` is true, pass the `created_at` of the last message to read the next page.'
        ),
})

/**
 * Add a message from the signed-in user to one of their tickets with the PostHog support team.
 * @summary Reply to a PostHog support ticket
 */
export const posthogSupportTicketsReplyCreatePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const PosthogSupportTicketsReplyCreateParams = () => zod.object({
    id: zod.string().regex(posthogSupportTicketsReplyCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const posthogSupportTicketsReplyCreateBodyMessageMax = 8000

export const PosthogSupportTicketsReplyCreateBody = () => zod.object({
    message: zod
        .string()
        .max(posthogSupportTicketsReplyCreateBodyMessageMax)
        .describe(
            'The reply in plain text, for example the details support asked for. Do not include secrets, API keys or personal data.'
        ),
})
