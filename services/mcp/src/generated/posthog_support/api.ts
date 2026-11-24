/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Saves a draft ticket to PostHog support. It does not send it. Refuses a topic that an agent can't file, and a plan without support for the topic, and says where the person can ask instead. The person approves it in chat, so the agent sends it with the send endpoint, or opens review_url to edit it and send it from the PostHog web app.
 * @summary Draft a PostHog support ticket for the person to approve
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
            "A short title that names the problem, such as 'Delete test events that contain customer emails'. It opens the ticket, and ticket lists show it, so don't start it with 'Request'."
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
            "Markdown bullets of facts support needs: the project and the region, a link to each object involved, SDK and version, and every required detail for the kind of request, such as a deletion query and its count. Link each object on its name, such as '- Project: [Web app](<link>)', and put the region on its own line. Take links from _posthogUrl. No guesses."
        ),
    already_checked: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAlreadyCheckedMax)
        .optional()
        .describe(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:' and link the page on its title, a lookup you ran in this conversation with '<your name> checked:', and a step the person took with 'I tried:'. When filing_reason is user_disagrees_with_agent or user_asked_for_support, this is required: add the answer you already gave them, with a link to each docs page it came from. List only your checks that bear on the open questions, because support can look up the rest of your calls. Never write a number the person gave you as your own check."
        ),
    error: zod
        .string()
        .max(posthogSupportDraftsCreateBodyErrorMax)
        .optional()
        .describe(
            'The exact text of an error the person saw, and its top frames. A lookup of yours that failed goes in already_checked. Remove any credential and say that you removed it.'
        ),
    topic: zod
        .enum([
            'privacy',
            'security',
            'compliance',
            'retention',
            'dpa',
            'baa',
            'privacy_or_security_deletion',
            'other_deletion',
            'billing',
            'other',
        ])
        .describe(
            '\* `privacy` - Privacy\n\* `security` - Security\n\* `compliance` - Compliance\n\* `retention` - Data retention\n\* `dpa` - Data processing agreement (DPA)\n\* `baa` - Business associate agreement (BAA)\n\* `privacy_or_security_deletion` - Deleting data for a privacy or security reason\n\* `other_deletion` - Deleting data for another reason\n\* `billing` - Billing or usage\n\* `other` - Anything else'
        )
        .describe(
            "What the ticket as a whole is about. Only privacy, security, compliance, retention, deletion, DPA, BAA and billing tickets can be filed from here. Use other for everything else, and don't stretch a topic to fit: support sees the topic. A login problem is other, never security. Use privacy_or_security_deletion only when the person gave a privacy or security reason for the deletion. Use billing only when the ticket is about billing or usage, not for a billing question asked in passing.\n\n\* `privacy` - Privacy\n\* `security` - Security\n\* `compliance` - Compliance\n\* `retention` - Data retention\n\* `dpa` - Data processing agreement (DPA)\n\* `baa` - Business associate agreement (BAA)\n\* `privacy_or_security_deletion` - Deleting data for a privacy or security reason\n\* `other_deletion` - Deleting data for another reason\n\* `billing` - Billing or usage\n\* `other` - Anything else"
        ),
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

/**
 * Posts the draft to PostHog support as the person, and returns the ticket. Call it only after the person saw the full ticket and approved sending it. A draft becomes at most one ticket: calling again returns the same ticket, and a draft sent from the review link can't be sent here.
 * @summary Send a drafted ticket to PostHog support after the person approved it
 */
export const posthogSupportDraftsSendCreatePathDraftIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const PosthogSupportDraftsSendCreateParams = () => zod.object({
    draft_id: zod.string().regex(posthogSupportDraftsSendCreatePathDraftIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
