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
 * Saves a draft ticket to PostHog support. It does not send it. The person opens review_url, checks and edits the ticket, and sends it from the PostHog web app.
 * @summary Draft a PostHog support ticket for the person to send
 */
export const PosthogSupportDraftsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const posthogSupportDraftsCreateBodyCustomerWordsMax = 4000

export const posthogSupportDraftsCreateBodyDetailsMax = 8000

export const posthogSupportDraftsCreateBodyAlreadyTriedMax = 4000

export const posthogSupportDraftsCreateBodyAgentNameMax = 100

export const PosthogSupportDraftsCreateBody = () => zod.object({
    customer_words: zod
        .string()
        .max(posthogSupportDraftsCreateBodyCustomerWordsMax)
        .describe(
            "The person's own description of the problem, quoted verbatim from what they wrote. Do not paraphrase it, and do not add your own diagnosis."
        ),
    filing_reason: zod
        .enum(['user_asked_for_support', 'account_or_billing', 'unexplained_error', 'user_disagrees_with_agent'])
        .describe(
            "\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `account_or_billing` - Account, billing or data only PostHog can see\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        )
        .describe(
            "Why a human should look at this. Draft only when the person asked for support, the problem involves account, billing or data only PostHog can see, there is a reproducible error you confirmed but cannot explain, or the person disagrees with your answer. Your own conclusion that it is a PostHog bug is not a reason.\n\n\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `account_or_billing` - Account, billing or data only PostHog can see\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        ),
    details: zod
        .string()
        .max(posthogSupportDraftsCreateBodyDetailsMax)
        .optional()
        .describe(
            'Facts the person gave or that you observed directly: exact error text, URLs, event and property names, the insight, flag or other object involved, SDK and version, when it started, and what they expected to happen. No guesses or conclusions.'
        ),
    already_tried: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAlreadyTriedMax)
        .optional()
        .describe('What the person and you already checked or tried, so support can judge the investigation.'),
    agent_name: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAgentNameMax)
        .optional()
        .describe('Name of the agent or client drafting the ticket, for example Claude Code or Codex.'),
})

/**
 * Deletes a draft without sending it.
 * @summary Discard a PostHog support ticket draft
 */
export const posthogSupportDraftsDiscardCreatePathDraftIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const PosthogSupportDraftsDiscardCreateParams = () => zod.object({
    draft_id: zod.string().regex(posthogSupportDraftsDiscardCreatePathDraftIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Tickets the logged-in user has raised with PostHog support, newest first.
 * @summary List your PostHog support tickets
 */
export const PosthogSupportTicketsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const posthogSupportTicketsRetrieveQueryLimitDefault = 20
export const posthogSupportTicketsRetrieveQueryLimitMax = 100

export const posthogSupportTicketsRetrieveQueryOffsetDefault = 0
export const posthogSupportTicketsRetrieveQueryOffsetMin = 0

export const PosthogSupportTicketsRetrieveQueryParams = () => zod.object({
    limit: zod
        .number()
        .min(1)
        .max(posthogSupportTicketsRetrieveQueryLimitMax)
        .default(posthogSupportTicketsRetrieveQueryLimitDefault)
        .describe('How many tickets to return.'),
    offset: zod
        .number()
        .min(posthogSupportTicketsRetrieveQueryOffsetMin)
        .default(posthogSupportTicketsRetrieveQueryOffsetDefault)
        .describe('How many tickets to skip, for paging.'),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            'Only return tickets with this status.\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        ),
})

/**
 * The messages on one of the logged-in user's PostHog support tickets, oldest first.
 * @summary Read one of your PostHog support tickets
 */
export const posthogSupportTicketsMessagesRetrievePathTicketIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const PosthogSupportTicketsMessagesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    ticket_id: zod.string().regex(posthogSupportTicketsMessagesRetrievePathTicketIdRegExp),
})
