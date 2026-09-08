/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Return credits spent in one conversation, by the calling product, and across PostHog AI, for the team's current billing period.
 * @summary Get a team's PostHog AI usage
 */
export const AiUsageRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AiUsageRetrieveQueryParams = () => zod.object({
    conversation_id: zod
        .string()
        .optional()
        .describe(
            'The conversation to report on, which is the `$ai_session_id` its generations carry: the Max conversation for a chat, the task for an agent run. Omitted, the report covers the team only.'
        ),
    conversation_started_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'When the conversation started. Only a Max conversation can be looked up here, so a caller that knows its own start time passes it; without one the reported period bounds the search and a conversation older than the period is undercounted.'
        ),
    product: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'The `ai_product` of the calling surface, e.g. `slack_app` or `posthog_code`. Adds a row for what that product alone spent. A product with no credit counter is reported as null.'
        ),
})

export const ConversationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ConversationsRetrieveParams = () => zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
