/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 19 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UserInterviewTopicsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsCreateBodyIntervieweeEmailsItemMax = 254

export const userInterviewTopicsCreateBodyIntervieweeDistinctIdsItemMax = 400

export const userInterviewTopicsCreateBodyInviteSubjectMax = 255

export const userInterviewTopicsCreateBodyInviteMessageMax = 1000

export const UserInterviewTopicsCreateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicsCreateBodyIntervieweeEmailsItemMax))
        .optional()
        .describe('Email addresses of people to interview. May be combined with interviewee_distinct_ids.'),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicsCreateBodyIntervieweeDistinctIdsItemMax))
        .optional()
        .describe('PostHog distinct IDs of people to interview. May be combined with interviewee_emails.'),
    topic: zod.string().describe('The product, feature, or idea you want to ask interviewees about.'),
    agent_context: zod
        .string()
        .optional()
        .describe('Optional additional system prompt for the voice agent — extra background, tone, or constraints.'),
    questions: zod
        .array(zod.string())
        .optional()
        .describe('Ordered list of questions the voice agent should work through during the interview.'),
    invite_subject: zod
        .string()
        .max(userInterviewTopicsCreateBodyInviteSubjectMax)
        .optional()
        .describe(
            'Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.'
        ),
    invite_message: zod
        .string()
        .max(userInterviewTopicsCreateBodyInviteMessageMax)
        .optional()
        .describe(
            'Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.'
        ),
})

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsPartialUpdateBodyIntervieweeEmailsItemMax = 254

export const userInterviewTopicsPartialUpdateBodyIntervieweeDistinctIdsItemMax = 400

export const userInterviewTopicsPartialUpdateBodyInviteSubjectMax = 255

export const userInterviewTopicsPartialUpdateBodyInviteMessageMax = 1000

export const UserInterviewTopicsPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicsPartialUpdateBodyIntervieweeEmailsItemMax))
        .optional()
        .describe('Email addresses of people to interview. May be combined with interviewee_distinct_ids.'),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicsPartialUpdateBodyIntervieweeDistinctIdsItemMax))
        .optional()
        .describe('PostHog distinct IDs of people to interview. May be combined with interviewee_emails.'),
    topic: zod.string().optional().describe('The product, feature, or idea you want to ask interviewees about.'),
    agent_context: zod
        .string()
        .optional()
        .describe('Optional additional system prompt for the voice agent — extra background, tone, or constraints.'),
    questions: zod
        .array(zod.string())
        .optional()
        .describe('Ordered list of questions the voice agent should work through during the interview.'),
    invite_subject: zod
        .string()
        .max(userInterviewTopicsPartialUpdateBodyInviteSubjectMax)
        .optional()
        .describe(
            'Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.'
        ),
    invite_message: zod
        .string()
        .max(userInterviewTopicsPartialUpdateBodyInviteMessageMax)
        .optional()
        .describe(
            'Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.'
        ),
})

/**
 * Add a single interviewee to this topic. Email-shaped identifiers (including the `Display Name <email@host>` form) are appended to `interviewee_emails`; everything else is appended to `interviewee_distinct_ids`. Idempotent — adding an identifier that's already present leaves the topic unchanged. Returns the updated topic.
 */
export const UserInterviewTopicsAddIntervieweeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsAddIntervieweeCreateBodyIdentifierMax = 400

export const UserInterviewTopicsAddIntervieweeCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(userInterviewTopicsAddIntervieweeCreateBodyIdentifierMax)
        .describe(
            'Email address or PostHog distinct ID for the interviewee. Email-shaped values (including the `Display Name <email@host>` form) are routed to `interviewee_emails`; everything else lands in `interviewee_distinct_ids`.'
        ),
})

/**
 * Generate one public interview link per targeted interviewee. Materializes an IntervieweeContext row for every identifier on the topic (without overwriting existing per-person context), and an enabled SharingConfiguration with a unique access token. The URL resolves to the public interview viewer with no PostHog auth required.
 */
export const UserInterviewTopicsGenerateLinksCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Same materialization as generate_links, returned as a downloadable CSV. Intended for users who want to mail-merge the per-person interview links into their own email tooling.
 */
export const UserInterviewTopicsLinksCsvCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Render the invite email exactly as a specific targeted interviewee would receive it — personalized subject and body — without sending anything and without creating or reading any share links. Pass `interviewee_identifier` to preview for a particular person, or omit it to preview for the first targeted interviewee. The body always shows an illustrative placeholder link (`is_preview_link: true`), never a live interview URL.
 */
export const UserInterviewTopicsPreviewInviteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsPreviewInviteCreateBodyIntervieweeIdentifierMax = 400

export const UserInterviewTopicsPreviewInviteCreateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsPreviewInviteCreateBodyIntervieweeIdentifierMax)
        .optional()
        .describe(
            'Which targeted interviewee to render the preview for (an email or PostHog distinct ID already on the topic). Leave blank to preview for the first targeted interviewee.'
        ),
})

/**
 * Remove an interviewee from this topic. Drops the identifier from both `interviewee_emails` and `interviewee_distinct_ids`, and disables any active SharingConfiguration linked to an IntervieweeContext for that identifier on this topic so the removed person can no longer open their interview link. Idempotent — removing an identifier that isn't present is a no-op. Returns the updated topic.
 */
export const UserInterviewTopicsRemoveIntervieweeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsRemoveIntervieweeCreateBodyIdentifierMax = 400

export const UserInterviewTopicsRemoveIntervieweeCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(userInterviewTopicsRemoveIntervieweeCreateBodyIdentifierMax)
        .describe(
            'Email address or PostHog distinct ID for the interviewee. Email-shaped values (including the `Display Name <email@host>` form) are routed to `interviewee_emails`; everything else lands in `interviewee_distinct_ids`.'
        ),
})

/**
 * Generate (if needed) and email a personalized public interview link to every targeted interviewee on this topic whose identifier is an email address. Distinct-ID-only interviewees are skipped and surfaced in the response. Each invite is keyed on the underlying SharingConfiguration so re-runs after token rotation produce a fresh send.
 */
export const UserInterviewTopicsSendInvitesCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsSendInvitesCreateBodySubjectMax = 200

export const userInterviewTopicsSendInvitesCreateBodySendAsyncDefault = true

export const UserInterviewTopicsSendInvitesCreateBody = /* @__PURE__ */ zod.object({
    subject: zod
        .string()
        .max(userInterviewTopicsSendInvitesCreateBodySubjectMax)
        .optional()
        .describe(
            "Override the email subject line for this send. Plain text only — URLs, angle brackets, and control characters are rejected. Falls back to the topic's saved subject, then a default."
        ),
    reply_to: zod
        .email()
        .optional()
        .describe("Email address replies should go to. Defaults to the topic creator's email if blank."),
    send_async: zod
        .boolean()
        .default(userInterviewTopicsSendInvitesCreateBodySendAsyncDefault)
        .describe(
            'If true (default), queue delivery via Celery. If false, send synchronously and surface errors immediately.'
        ),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const UserInterviewTopicsIntervieweesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const userInterviewTopicsIntervieweesCreateBodyIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesCreateBodyAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesCreateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsIntervieweesCreateBodyIntervieweeIdentifierMax)
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(userInterviewTopicsIntervieweesCreateBodyAgentContextMax)
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this interviewee context.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const userInterviewTopicsIntervieweesPartialUpdateBodyIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesPartialUpdateBodyAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsIntervieweesPartialUpdateBodyIntervieweeIdentifierMax)
        .optional()
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(userInterviewTopicsIntervieweesPartialUpdateBodyAgentContextMax)
        .optional()
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this interviewee context.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

/**
 * Create up to 500 interviewee context rows for a topic in a single request. Rows whose (topic, interviewee_identifier) already exists are skipped — the response surfaces an `inserted_count`, a `skipped_count`, and the `skipped_identifiers` so the caller can reconcile. Items must have unique `interviewee_identifier` values within the batch.
 */
export const UserInterviewTopicsIntervieweesBulkCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const userInterviewTopicsIntervieweesBulkCreateBodyItemsItemIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesBulkCreateBodyItemsItemAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesBulkCreateBody = /* @__PURE__ */ zod.object({
    items: zod
        .array(
            zod.object({
                interviewee_identifier: zod
                    .string()
                    .max(userInterviewTopicsIntervieweesBulkCreateBodyItemsItemIntervieweeIdentifierMax)
                    .describe(
                        "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
                    ),
                agent_context: zod
                    .string()
                    .max(userInterviewTopicsIntervieweesBulkCreateBodyItemsItemAgentContextMax)
                    .describe(
                        "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
                    ),
            })
        )
        .describe(
            'List of interviewee context rows to create. Each item has an `interviewee_identifier` and an `agent_context`. At most 500 items per request.'
        ),
})

export const UserInterviewsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UserInterviewsListQueryParams = /* @__PURE__ */ zod.object({
    classifications: zod
        .string()
        .optional()
        .describe(
            'Comma-separated classifications; returns responses carrying any of them (OR). Valid values: abandoned, off-topic.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    topic: zod.string().optional(),
})

export const UserInterviewsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UserInterviewsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    classifications: zod
        .array(zod.enum(['abandoned', 'off-topic']).describe('* `abandoned` - Abandoned\n* `off-topic` - Off-topic'))
        .optional()
        .describe(
            'Searchable classifications on the response. `abandoned` is auto-derived from the transcript when the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update replaces the whole list — pass the full desired set, not a delta.'
        ),
    audio: zod.url().optional(),
})

/**
 * Embed `query` with the same model used to index interview transcripts and summaries, then return the top matches by cosine distance. Each match is a single (interview, document_type) pair — an interview can appear up to twice if both its transcript and summary score above other interviews. Useful for surfacing relevant interview snippets in natural language, without exact keyword matches.
 * @summary Search interview responses by semantic similarity
 */
export const UserInterviewsSearchCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewsSearchCreateBodyQueryMax = 2000

export const userInterviewsSearchCreateBodyLimitMax = 50

export const UserInterviewsSearchCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .max(userInterviewsSearchCreateBodyQueryMax)
        .describe('Natural-language query to match semantically against interview transcripts and summaries.'),
    document_types: zod
        .array(zod.enum(['transcript', 'summary']).describe('* `transcript` - transcript\n* `summary` - summary'))
        .min(1)
        .optional()
        .describe(
            'Which document types to search across. Omit to default to both `transcript` and `summary`. Pass a non-empty subset to restrict the search.'
        ),
    topic_id: zod
        .uuid()
        .nullish()
        .describe('Optional. Restrict results to interviews belonging to a specific UserInterviewTopic.'),
    classifications: zod
        .array(zod.enum(['abandoned', 'off-topic']).describe('* `abandoned` - Abandoned\n* `off-topic` - Off-topic'))
        .min(1)
        .optional()
        .describe(
            'Optional. Restrict results to interviews carrying any of these classifications (OR). Combines with `topic_id` as AND.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(userInterviewsSearchCreateBodyLimitMax)
        .optional()
        .describe(
            'Maximum number of matches to return (1-50). Defaults to 10. Two matches per interview are possible — one for the transcript, one for the summary.'
        ),
})
