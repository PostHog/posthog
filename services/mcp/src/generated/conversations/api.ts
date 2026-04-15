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
    assignee: zod
        .string()
        .optional()
        .describe(
            'Filter by assignee. Use `unassigned` for tickets with no assignee, `user:<user_id>` for a specific user, or `role:<role_uuid>` for a role.'
        ),
    channel_detail: zod
        .enum(['slack_bot_mention', 'slack_channel_message', 'slack_emoji_reaction', 'widget_api', 'widget_embedded'])
        .optional()
        .describe('Filter by the channel sub-type (e.g. `widget_embedded`, `slack_bot_mention`).'),
    channel_source: zod
        .enum(['email', 'slack', 'widget'])
        .optional()
        .describe('Filter by the channel the ticket originated from.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            'Only include tickets updated on or after this date. Accepts absolute dates (`2026-01-01`) or relative ones (`-7d`, `-1mStart`). Pass `all` to disable the filter.'
        ),
    date_to: zod
        .string()
        .optional()
        .describe('Only include tickets updated on or before this date. Same format as `date_from`.'),
    distinct_ids: zod
        .string()
        .optional()
        .describe('Comma-separated list of person `distinct_id`s to filter by (max 100).'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .enum([
            '-created_at',
            '-sla_due_at',
            '-ticket_number',
            '-updated_at',
            'created_at',
            'sla_due_at',
            'ticket_number',
            'updated_at',
        ])
        .optional()
        .describe('Sort order. Prefix with `-` for descending. Defaults to `-updated_at`.'),
    priority: zod
        .string()
        .optional()
        .describe(
            'Filter by priority. Accepts a single value or a comma-separated list (e.g. `medium,high`). Valid values: `low`, `medium`, `high`.'
        ),
    search: zod
        .string()
        .optional()
        .describe(
            "Free-text search. A numeric value matches a ticket number exactly; otherwise matches against the customer's name or email (case-insensitive, partial match)."
        ),
    sla: zod
        .enum(['at-risk', 'breached', 'on-track'])
        .optional()
        .describe(
            'Filter by SLA state. `breached` = past `sla_due_at`, `at-risk` = due within the next hour, `on-track` = more than an hour remaining.'
        ),
    status: zod
        .string()
        .optional()
        .describe(
            'Filter by status. Accepts a single value or a comma-separated list (e.g. `new,open,pending`). Valid values: `new`, `open`, `pending`, `on_hold`, `resolved`.'
        ),
    tags: zod
        .string()
        .optional()
        .describe('JSON-encoded array of tag names to filter by, e.g. `["billing","urgent"]`.'),
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
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({}).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')
