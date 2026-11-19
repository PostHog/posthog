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

export const posthogSupportDraftsCreateBodyTitleMax = 100

export const posthogSupportDraftsCreateBodyRequestMax = 2000

export const posthogSupportDraftsCreateBodyDetailsMax = 3000

export const posthogSupportDraftsCreateBodyAlreadyCheckedMax = 1500

export const posthogSupportDraftsCreateBodyErrorMax = 1500

export const posthogSupportDraftsCreateBodyAgentNameOneRegExp = new RegExp('^[\\w .\\-]{1,40}$')
export const posthogSupportDraftsCreateBodyAgentNameTwoMax = 0

export const PosthogSupportDraftsCreateBody = () => zod.object({
    title: zod
        .string()
        .max(posthogSupportDraftsCreateBodyTitleMax)
        .describe(
            "A short title that names the problem, such as 'Experiment exposures split 90\/10 instead of 50\/50'. It opens the ticket, and ticket lists show it, so don't start it with 'Request'."
        ),
    request: zod
        .string()
        .max(posthogSupportDraftsCreateBodyRequestMax)
        .describe(
            "The whole ask, in the person's voice. Open with what happened in one sentence, with the numbers and dates. Then add the action they need in one sentence, or list every question the docs did not answer, numbered in the person's order, with every part of each question. When they heard your answer and still want a human, give your answer in one sentence, as yours."
        ),
    details: zod
        .string()
        .max(posthogSupportDraftsCreateBodyDetailsMax)
        .optional()
        .describe(
            "Markdown bullets of facts support needs: the project and the region, a link to each object involved, SDK and version, and every required detail for the kind of request, such as a deletion query and its count. Link each object on its name, then give its ID, such as '- Experiment: [Checkout test](<link>) (ID 3)', and put the region on its own line. Take links from _posthogUrl. No guesses."
        ),
    already_checked: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAlreadyCheckedMax)
        .optional()
        .describe(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:' and link the page on its title, a lookup you ran in this conversation with '<your name> checked:', and a step the person took with 'I tried:'. List only your checks that bear on the open questions, because support can look up the rest of your calls. Never write a number the person gave you as your own check."
        ),
    error: zod
        .string()
        .max(posthogSupportDraftsCreateBodyErrorMax)
        .optional()
        .describe(
            'The exact text of an error the person saw, and its top frames. A lookup of yours that failed goes in already_checked. Remove any credential and say that you removed it.'
        ),
    filing_reason: zod
        .enum([
            'user_asked_for_support',
            'needs_posthog_staff',
            'billing_question',
            'unexplained_error',
            'user_disagrees_with_agent',
        ])
        .describe(
            "\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `billing_question` - A billing or usage question, which PostHog answers on every plan\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        )
        .describe(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason. Use billing_question only when the ticket is about billing or usage, not for a billing question asked in passing in a ticket about something else.\n\n\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `billing_question` - A billing or usage question, which PostHog answers on every plan\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        ),
    agent_name: zod
        .union([
            zod.string().regex(posthogSupportDraftsCreateBodyAgentNameOneRegExp),
            zod.string().max(posthogSupportDraftsCreateBodyAgentNameTwoMax),
        ])
        .optional()
        .describe('Name of the agent or client drafting the ticket, such as Claude Code or Codex.'),
})
