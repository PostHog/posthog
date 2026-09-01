/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsListQueryParams = /* @__PURE__ */ zod.object({
    ai_triage_result: zod
        .string()
        .optional()
        .describe(
            'Filter by AI triage outcome. Accepts a single value or a comma-separated list. Valid values: `persisted`, `escalated_with_best`, `escalated_no_reply`, `skipped_unactionable`, `blocked_unsafe`, `blocked_unsafe_reply`, `in_progress`.'
        ),
    assignee: zod
        .string()
        .optional()
        .describe(
            'Filter by assignee. Accepts a single value or a comma-separated list (matches any, max 100 entries). Each entry is `unassigned` (no assignee), `me` (the requesting user), `user:<user_id>`, or `role:<role_uuid>`, e.g. `assignee=unassigned,user:123`.'
        ),
    channel_detail: zod
        .enum([
            'github_issue',
            'slack_bot_mention',
            'slack_channel_message',
            'slack_emoji_reaction',
            'teams_bot_mention',
            'teams_channel_message',
            'widget_api',
            'widget_embedded',
        ])
        .optional()
        .describe('Filter by the channel sub-type (e.g. `widget_embedded`, `slack_bot_mention`).'),
    channel_source: zod
        .enum(['email', 'github', 'slack', 'teams', 'widget'])
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
    emails: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of email addresses to filter by, matched case-insensitively against `email_from` (max 100). When combined with `distinct_ids`, tickets matching either the distinct_ids or the emails are returned (OR).'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe('Sort order. Prefix with `-` for descending. Defaults to `-updated_at`.'),
    priority: zod
        .string()
        .optional()
        .describe(
            'Filter by priority. Accepts a single value or a comma-separated list (e.g. `medium,high`). Valid values: `low`, `medium`, `high`, `critical`.'
        ),
    search: zod
        .string()
        .optional()
        .describe(
            "Free-text search. A numeric value (optionally prefixed with `#`) matches a ticket number exactly; otherwise matches against the customer's name or email, the email subject, or message content (case-insensitive, partial match)."
        ),
    sla: zod
        .enum(['at-risk', 'breached', 'on-track'])
        .optional()
        .describe(
            'Filter by SLA state. `breached` = past `sla_due_at`, `at-risk` = due within the next hour, `on-track` = more than an hour remaining.'
        ),
    snoozed: zod
        .boolean()
        .optional()
        .describe('Filter by snooze state: `true` returns only snoozed tickets, `false` only non-snoozed.'),
    status: zod
        .string()
        .optional()
        .describe(
            'Filter by status. Accepts a single value or a comma-separated list (e.g. `new,open,pending`). Valid values: `new`, `open`, `pending`, `on_hold`, `resolved`.'
        ),
    tags: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded array of tag names; returns tickets with ANY of them (OR), e.g. `[\"billing\",\"urgent\"]`.'
        ),
    tags_all: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded array of tag names; returns tickets that have ALL of them (AND), e.g. `[\"billing\",\"urgent\"]`.'
        ),
    tags_exclude: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded array of tag names; returns tickets that have NONE of them (NOT), e.g. `[\"escalated\"]`.'
        ),
    view: zod
        .string()
        .optional()
        .describe(
            "Apply a saved ticket view's filters by its `short_id` (list views via the `conversations\/views` endpoint). Any filter param passed explicitly overrides the view's saved value for that dimension. Returns 400 if no view matches."
        ),
})

/**
 * Get single ticket and mark as read by team.
 */
export const ConversationsTicketsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved.\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'critical'])
                    .describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Ticket priority: low, medium, high, or critical. Pass null to clear it.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical'
            ),
        assignee: zod
            .union([
                zod.union([
                    zod.object({
                        type: zod.enum(['user']).describe('Assign the ticket to a user.'),
                        id: zod.number().describe('User ID.'),
                    }),
                    zod.object({
                        type: zod.enum(['role']).describe('Assign the ticket to a role.'),
                        id: zod.string().describe('Role ID.'),
                    }),
                ]),
                zod.null(),
            ])
            .optional()
            .describe('User or role to assign. Pass null to remove the current assignee.'),
        sla_due_at: zod.iso.datetime({ offset: true }).nullish().describe('SLA deadline. Pass null to clear it.'),
        snoozed_until: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Time to reopen the ticket. Pass null to reopen it now.'),
        tags: zod.array(zod.string()).optional().describe('Tag names to set on the ticket.'),
    })
    .describe('Fields accepted when updating a ticket.')

/**
 * Return the message thread for a ticket, ordered chronologically (paginated).
 */
export const ConversationsTicketsMessagesListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsMessagesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Update a private note on a ticket.
 *
 * Only the note's author can edit it. Customer-facing replies cannot be
 * edited (outbound delivery only runs on create).
 */
export const ConversationsTicketsNotesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    message_id: zod.string().describe('The UUID of the private note (comment) to edit or delete.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const conversationsTicketsNotesPartialUpdateBodyMessageMax = 5000

export const ConversationsTicketsNotesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        message: zod
            .string()
            .max(conversationsTicketsNotesPartialUpdateBodyMessageMax)
            .optional()
            .describe('Updated note content in markdown.'),
        rich_content: zod
            .unknown()
            .optional()
            .describe(
                'Optional TipTap rich content JSON. Omit or pass null to clear previous rich content so the thread falls back to the markdown message.'
            ),
    })
    .describe('Payload for updating a private note on a ticket.')

/**
 * Soft-delete a private note on a ticket.
 *
 * Only the note's author can delete it. Customer-facing replies cannot be
 * deleted via this endpoint.
 */
export const ConversationsTicketsNotesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    message_id: zod.string().describe('The UUID of the private note (comment) to edit or delete.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Post a reply or internal note to a ticket.
 *
 * With is_private=false, the reply is delivered to the customer via the
 * ticket's channel (email, Slack, Teams, GitHub). With is_private=true,
 * the message is stored as an internal note only visible to team members.
 *
 * Retrying an identical message from the same author within a short window returns the
 * original message with a 200 rather than posting it twice, and a 409 while a concurrent
 * request is still creating it.
 */
export const ConversationsTicketsReplyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const conversationsTicketsReplyCreateBodyMessageMax = 5000

export const conversationsTicketsReplyCreateBodyIsPrivateDefault = false

export const ConversationsTicketsReplyCreateBody = /* @__PURE__ */ zod
    .object({
        message: zod.string().max(conversationsTicketsReplyCreateBodyMessageMax).describe('Reply content in markdown.'),
        is_private: zod
            .boolean()
            .default(conversationsTicketsReplyCreateBodyIsPrivateDefault)
            .describe(
                "If true, store as an internal note (not sent to the customer). If false, the reply is delivered to the customer over the ticket's channel."
            ),
        rich_content: zod.unknown().optional().describe('Optional TipTap rich content JSON for formatted messages.'),
    })
    .describe('Payload for posting a reply or internal note to a ticket.')

export const ConversationsViewsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsViewsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})
