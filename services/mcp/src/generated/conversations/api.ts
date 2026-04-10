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
 * List tickets with person data attached.
 */
export const ConversationsTicketsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get single ticket and mark as read by team.
 */
export const ConversationsTicketsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n* `low` - Low\n* `medium` - Medium\n* `high` - High'
            ),
        escalation_reason: zod.string().nullish().describe('Reason the ticket was escalated from AI to human'),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')
