/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
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

export const posthogSupportDraftsCreateBodyRequestMax = 1000

export const posthogSupportDraftsCreateBodyDetailsMax = 3000

export const posthogSupportDraftsCreateBodyAlreadyCheckedMax = 1500

export const posthogSupportDraftsCreateBodyLeftForSupportMax = 500

export const posthogSupportDraftsCreateBodyErrorMax = 1500

export const posthogSupportDraftsCreateBodyAgentNameOneRegExp = new RegExp('^[\\w .\\-]{1,40}$')
export const posthogSupportDraftsCreateBodyAgentNameTwoMax = 0

export const PosthogSupportDraftsCreateBody = () => zod.object({
    request: zod
        .string()
        .max(posthogSupportDraftsCreateBodyRequestMax)
        .describe(
            'What the person needs PostHog to do or answer, in one to three sentences, in their own words. Put each question they asked on its own line.'
        ),
    details: zod
        .string()
        .max(posthogSupportDraftsCreateBodyDetailsMax)
        .optional()
        .describe(
            'Markdown bullets of facts support needs: the project name, ID, region and link, links to the objects involved, SDK and version, and every required detail for the kind of request, such as a deletion query and its count. Take links from _posthogUrl. No guesses.'
        ),
    already_checked: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAlreadyCheckedMax)
        .optional()
        .describe(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:', one of yours with '<your name> checked:', and one of the person's with 'I tried:'."
        ),
    left_for_support: zod
        .string()
        .max(posthogSupportDraftsCreateBodyLeftForSupportMax)
        .describe(
            "The one thing only PostHog can do or confirm, such as 'Delete the 3,817 events this query returns'."
        ),
    error: zod
        .string()
        .max(posthogSupportDraftsCreateBodyErrorMax)
        .optional()
        .describe('The exact error text and its top frames. Remove any credential and say that you removed it.'),
    filing_reason: zod
        .enum(['user_asked_for_support', 'needs_posthog_staff', 'unexplained_error', 'user_disagrees_with_agent'])
        .describe(
            "\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        )
        .describe(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason.\n\n\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        ),
    agent_name: zod
        .union([
            zod.string().regex(posthogSupportDraftsCreateBodyAgentNameOneRegExp),
            zod.string().max(posthogSupportDraftsCreateBodyAgentNameTwoMax),
        ])
        .optional()
        .describe('Name of the agent or client drafting the ticket, such as Claude Code or Codex.'),
})
