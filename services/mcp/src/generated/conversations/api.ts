/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List tickets with person data attached.
 */
export const ConversationsTicketsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsListQueryParams = () => zod.object({
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
export const ConversationsTicketsRetrieveParams = () => zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsPartialUpdateParams = () => zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsPartialUpdateBody = () => zod
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
export const ConversationsTicketsMessagesListParams = () => zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsTicketsMessagesListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Update a private note on a ticket.
 *
 * Only the note's author can edit it. Customer-facing replies cannot be
 * edited (outbound delivery only runs on create).
 */
export const ConversationsTicketsNotesPartialUpdateParams = () => zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    message_id: zod.string().describe('The UUID of the private note (comment) to edit or delete.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const conversationsTicketsNotesPartialUpdateBodyMessageMax = 5000

export const ConversationsTicketsNotesPartialUpdateBody = () => zod
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
export const ConversationsTicketsNotesDestroyParams = () => zod.object({
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
export const ConversationsTicketsReplyCreateParams = () => zod.object({
    id: zod.string().describe("The ticket's UUID or its numeric ticket number."),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const conversationsTicketsReplyCreateBodyMessageMax = 5000

export const conversationsTicketsReplyCreateBodyIsPrivateDefault = false

export const ConversationsTicketsReplyCreateBody = () => zod
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

export const ConversationsViewsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ConversationsViewsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ConversationsViewsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const conversationsViewsCreateBodyNameMax = 400

export const conversationsViewsCreateBodyFiltersOneSearchMax = 200

export const ConversationsViewsCreateBody = () => zod.object({
    name: zod
        .string()
        .max(conversationsViewsCreateBodyNameMax)
        .describe('Display name of the view, as it appears in the ticket views list.'),
    filters: zod
        .object({
            status: zod
                .array(
                    zod
                        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
                        .describe(
                            '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
                        )
                )
                .optional()
                .describe('Ticket statuses to include. Empty or omitted means all statuses.'),
            priority: zod
                .array(
                    zod
                        .enum(['low', 'medium', 'high', 'critical'])
                        .describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical')
                )
                .optional()
                .describe('Ticket priorities to include. Empty or omitted means all priorities.'),
            channel: zod
                .enum(['widget', 'email', 'slack', 'teams', 'github', 'all'])
                .describe(
                    '\* `widget` - widget\n\* `email` - email\n\* `slack` - slack\n\* `teams` - teams\n\* `github` - github\n\* `all` - all'
                )
                .optional()
                .describe(
                    "Channel the ticket originated from. 'all' disables the filter.\n\n\* `widget` - widget\n\* `email` - email\n\* `slack` - slack\n\* `teams` - teams\n\* `github` - github\n\* `all` - all"
                ),
            sla: zod
                .enum(['breached', 'at-risk', 'on-track', 'all'])
                .describe('\* `breached` - breached\n\* `at-risk` - at-risk\n\* `on-track` - on-track\n\* `all` - all')
                .optional()
                .describe(
                    "SLA state: 'breached' is past due, 'at-risk' is due within the next hour, 'on-track' has more than an hour remaining. 'all' disables the filter.\n\n\* `breached` - breached\n\* `at-risk` - at-risk\n\* `on-track` - on-track\n\* `all` - all"
                ),
            aiTriageResult: zod
                .array(
                    zod
                        .enum([
                            'persisted',
                            'escalated_with_best',
                            'escalated_no_reply',
                            'skipped_unactionable',
                            'blocked_unsafe',
                            'blocked_unsafe_reply',
                            'in_progress',
                        ])
                        .describe(
                            '\* `persisted` - persisted\n\* `escalated_with_best` - escalated_with_best\n\* `escalated_no_reply` - escalated_no_reply\n\* `skipped_unactionable` - skipped_unactionable\n\* `blocked_unsafe` - blocked_unsafe\n\* `blocked_unsafe_reply` - blocked_unsafe_reply\n\* `in_progress` - in_progress'
                        )
                )
                .optional()
                .describe("AI triage outcomes to include. 'in_progress' matches tickets still being triaged."),
            assignee: zod
                .array(
                    zod.union([
                        zod.enum(['me', 'unassigned']),
                        zod.object({
                            type: zod.enum(['user', 'role']),
                            id: zod.union([zod.string(), zod.number()]),
                        }),
                    ])
                )
                .optional()
                .describe(
                    "Assignees to match (any of): 'unassigned', 'me' (resolved to the requesting user), or an object with type ('user' or 'role') and id. The legacy single-value shape is accepted and normalized to a list."
                ),
            tags: zod.array(zod.string()).optional().describe('Tag names to match, combined according to tagsMatch.'),
            tagsMatch: zod
                .enum(['any', 'all'])
                .describe('\* `any` - any\n\* `all` - all')
                .optional()
                .describe(
                    "'any' returns tickets with at least one of tags (OR); 'all' requires every tag (AND).\n\n\* `any` - any\n\* `all` - all"
                ),
            tagsExclude: zod
                .array(zod.string())
                .optional()
                .describe('Tickets carrying any of these tags are excluded.'),
            dateFrom: zod
                .string()
                .nullish()
                .describe(
                    "Only include tickets updated on or after this date. Accepts absolute dates (2026-01-01) or relative ones (-7d). 'all' or null disables the bound."
                ),
            dateTo: zod
                .string()
                .nullish()
                .describe('Only include tickets updated on or before this date. Same format as dateFrom.'),
            sorting: zod
                .union([
                    zod.object({
                        columnKey: zod
                            .string()
                            .describe(
                                'Ticket column to sort by (updated_at, sla_due_at, snoozed_until, created_at, ticket_number). Unknown columns fall back to updated_at.'
                            ),
                        order: zod
                            .union([zod.literal(1), zod.literal(-1)])
                            .describe('\* `1` - 1\n\* `-1` - -1')
                            .describe('1 for ascending, -1 for descending.\n\n\* `1` - 1\n\* `-1` - -1'),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Sort order for the ticket list.'),
            search: zod
                .string()
                .max(conversationsViewsCreateBodyFiltersOneSearchMax)
                .optional()
                .describe(
                    "Free-text search. A numeric value matches a ticket number exactly; otherwise matches the customer's name or email, the email subject, or message content."
                ),
        })
        .describe(
            "Canonical shape of a saved ticket view's filters. Every field is optional; an omitted\nfield (or an 'all' sentinel) leaves that dimension unfiltered."
        )
        .optional()
        .describe(
            'Saved ticket filter criteria: status, priority, channel, sla, aiTriageResult, assignee, tags, tagsMatch, tagsExclude, dateFrom, dateTo, sorting, and search.'
        ),
    is_favorited: zod
        .boolean()
        .optional()
        .describe(
            'Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.'
        ),
})

export const ConversationsViewsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const ConversationsViewsPartialUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const conversationsViewsPartialUpdateBodyNameMax = 400

export const conversationsViewsPartialUpdateBodyFiltersOneSearchMax = 200

export const ConversationsViewsPartialUpdateBody = () => zod.object({
    name: zod
        .string()
        .max(conversationsViewsPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name of the view, as it appears in the ticket views list.'),
    filters: zod
        .object({
            status: zod
                .array(
                    zod
                        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
                        .describe(
                            '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
                        )
                )
                .optional()
                .describe('Ticket statuses to include. Empty or omitted means all statuses.'),
            priority: zod
                .array(
                    zod
                        .enum(['low', 'medium', 'high', 'critical'])
                        .describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical')
                )
                .optional()
                .describe('Ticket priorities to include. Empty or omitted means all priorities.'),
            channel: zod
                .enum(['widget', 'email', 'slack', 'teams', 'github', 'all'])
                .describe(
                    '\* `widget` - widget\n\* `email` - email\n\* `slack` - slack\n\* `teams` - teams\n\* `github` - github\n\* `all` - all'
                )
                .optional()
                .describe(
                    "Channel the ticket originated from. 'all' disables the filter.\n\n\* `widget` - widget\n\* `email` - email\n\* `slack` - slack\n\* `teams` - teams\n\* `github` - github\n\* `all` - all"
                ),
            sla: zod
                .enum(['breached', 'at-risk', 'on-track', 'all'])
                .describe('\* `breached` - breached\n\* `at-risk` - at-risk\n\* `on-track` - on-track\n\* `all` - all')
                .optional()
                .describe(
                    "SLA state: 'breached' is past due, 'at-risk' is due within the next hour, 'on-track' has more than an hour remaining. 'all' disables the filter.\n\n\* `breached` - breached\n\* `at-risk` - at-risk\n\* `on-track` - on-track\n\* `all` - all"
                ),
            aiTriageResult: zod
                .array(
                    zod
                        .enum([
                            'persisted',
                            'escalated_with_best',
                            'escalated_no_reply',
                            'skipped_unactionable',
                            'blocked_unsafe',
                            'blocked_unsafe_reply',
                            'in_progress',
                        ])
                        .describe(
                            '\* `persisted` - persisted\n\* `escalated_with_best` - escalated_with_best\n\* `escalated_no_reply` - escalated_no_reply\n\* `skipped_unactionable` - skipped_unactionable\n\* `blocked_unsafe` - blocked_unsafe\n\* `blocked_unsafe_reply` - blocked_unsafe_reply\n\* `in_progress` - in_progress'
                        )
                )
                .optional()
                .describe("AI triage outcomes to include. 'in_progress' matches tickets still being triaged."),
            assignee: zod
                .array(
                    zod.union([
                        zod.enum(['me', 'unassigned']),
                        zod.object({
                            type: zod.enum(['user', 'role']),
                            id: zod.union([zod.string(), zod.number()]),
                        }),
                    ])
                )
                .optional()
                .describe(
                    "Assignees to match (any of): 'unassigned', 'me' (resolved to the requesting user), or an object with type ('user' or 'role') and id. The legacy single-value shape is accepted and normalized to a list."
                ),
            tags: zod.array(zod.string()).optional().describe('Tag names to match, combined according to tagsMatch.'),
            tagsMatch: zod
                .enum(['any', 'all'])
                .describe('\* `any` - any\n\* `all` - all')
                .optional()
                .describe(
                    "'any' returns tickets with at least one of tags (OR); 'all' requires every tag (AND).\n\n\* `any` - any\n\* `all` - all"
                ),
            tagsExclude: zod
                .array(zod.string())
                .optional()
                .describe('Tickets carrying any of these tags are excluded.'),
            dateFrom: zod
                .string()
                .nullish()
                .describe(
                    "Only include tickets updated on or after this date. Accepts absolute dates (2026-01-01) or relative ones (-7d). 'all' or null disables the bound."
                ),
            dateTo: zod
                .string()
                .nullish()
                .describe('Only include tickets updated on or before this date. Same format as dateFrom.'),
            sorting: zod
                .union([
                    zod.object({
                        columnKey: zod
                            .string()
                            .describe(
                                'Ticket column to sort by (updated_at, sla_due_at, snoozed_until, created_at, ticket_number). Unknown columns fall back to updated_at.'
                            ),
                        order: zod
                            .union([zod.literal(1), zod.literal(-1)])
                            .describe('\* `1` - 1\n\* `-1` - -1')
                            .describe('1 for ascending, -1 for descending.\n\n\* `1` - 1\n\* `-1` - -1'),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Sort order for the ticket list.'),
            search: zod
                .string()
                .max(conversationsViewsPartialUpdateBodyFiltersOneSearchMax)
                .optional()
                .describe(
                    "Free-text search. A numeric value matches a ticket number exactly; otherwise matches the customer's name or email, the email subject, or message content."
                ),
        })
        .describe(
            "Canonical shape of a saved ticket view's filters. Every field is optional; an omitted\nfield (or an 'all' sentinel) leaves that dimension unfiltered."
        )
        .optional()
        .describe(
            'Saved ticket filter criteria: status, priority, channel, sla, aiTriageResult, assignee, tags, tagsMatch, tagsExclude, dateFrom, dateTo, sorting, and search.'
        ),
    is_favorited: zod
        .boolean()
        .optional()
        .describe(
            'Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.'
        ),
})
