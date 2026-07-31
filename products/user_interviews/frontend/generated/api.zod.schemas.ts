/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const userInterviewTopicApiIntervieweeEmailsItemMax = 254

export const userInterviewTopicApiIntervieweeDistinctIdsItemMax = 400

export const userInterviewTopicApiInviteSubjectMax = 255

export const userInterviewTopicApiInviteMessageMax = 1000

export const UserInterviewTopicApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicApiIntervieweeEmailsItemMax))
        .optional()
        .describe('Email addresses of people to interview. May be combined with interviewee_distinct_ids.'),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicApiIntervieweeDistinctIdsItemMax))
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
        .max(userInterviewTopicApiInviteSubjectMax)
        .optional()
        .describe(
            'Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.'
        ),
    invite_message: zod
        .string()
        .max(userInterviewTopicApiInviteMessageMax)
        .optional()
        .describe(
            'Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.'
        ),
})

export type UserInterviewTopicApi = zod.input<typeof UserInterviewTopicApi>
export type UserInterviewTopicApiOutput = zod.output<typeof UserInterviewTopicApi>

export const PaginatedUserInterviewTopicListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(UserInterviewTopicApi),
})

export type PaginatedUserInterviewTopicListApi = zod.input<typeof PaginatedUserInterviewTopicListApi>
export type PaginatedUserInterviewTopicListApiOutput = zod.output<typeof PaginatedUserInterviewTopicListApi>

export const patchedUserInterviewTopicApiIntervieweeEmailsItemMax = 254

export const patchedUserInterviewTopicApiIntervieweeDistinctIdsItemMax = 400

export const patchedUserInterviewTopicApiInviteSubjectMax = 255

export const patchedUserInterviewTopicApiInviteMessageMax = 1000

export const PatchedUserInterviewTopicApi = zod.object({
    id: zod.uuid().optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    interviewee_emails: zod
        .array(zod.string().max(patchedUserInterviewTopicApiIntervieweeEmailsItemMax))
        .optional()
        .describe('Email addresses of people to interview. May be combined with interviewee_distinct_ids.'),
    interviewee_distinct_ids: zod
        .array(zod.string().max(patchedUserInterviewTopicApiIntervieweeDistinctIdsItemMax))
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
        .max(patchedUserInterviewTopicApiInviteSubjectMax)
        .optional()
        .describe(
            'Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.'
        ),
    invite_message: zod
        .string()
        .max(patchedUserInterviewTopicApiInviteMessageMax)
        .optional()
        .describe(
            'Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.'
        ),
})

export type PatchedUserInterviewTopicApi = zod.input<typeof PatchedUserInterviewTopicApi>
export type PatchedUserInterviewTopicApiOutput = zod.output<typeof PatchedUserInterviewTopicApi>

export const intervieweeIdentifierRequestApiIdentifierMax = 400

export const IntervieweeIdentifierRequestApi = zod.object({
    identifier: zod
        .string()
        .max(intervieweeIdentifierRequestApiIdentifierMax)
        .describe(
            'Email address or PostHog distinct ID for the interviewee. Email-shaped values (including the `Display Name <email@host>` form) are routed to `interviewee_emails`; everything else lands in `interviewee_distinct_ids`.'
        ),
})

export type IntervieweeIdentifierRequestApi = zod.input<typeof IntervieweeIdentifierRequestApi>
export type IntervieweeIdentifierRequestApiOutput = zod.output<typeof IntervieweeIdentifierRequestApi>

export const interviewLinkApiIntervieweeIdentifierMax = 400

export const InterviewLinkApi = zod.object({
    interviewee_identifier: zod
        .string()
        .max(interviewLinkApiIntervieweeIdentifierMax)
        .describe('The original identifier (email or distinct ID) from the topic targeting.'),
    user_name: zod
        .string()
        .describe('Best-effort display name derived from the identifier, used to greet the interviewee.'),
    interview_url: zod
        .url()
        .describe(
            'Public, unauthenticated URL the interviewee opens to start the call. Backed by a SharingConfiguration access token.'
        ),
    agent_context: zod
        .string()
        .describe('The merged topic + per-interviewee context the voice agent will see during the call.'),
})

export type InterviewLinkApi = zod.input<typeof InterviewLinkApi>
export type InterviewLinkApiOutput = zod.output<typeof InterviewLinkApi>

export const PaginatedInterviewLinkListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(InterviewLinkApi),
})

export type PaginatedInterviewLinkListApi = zod.input<typeof PaginatedInterviewLinkListApi>
export type PaginatedInterviewLinkListApiOutput = zod.output<typeof PaginatedInterviewLinkListApi>

export const previewInviteRequestApiIntervieweeIdentifierMax = 400

export const PreviewInviteRequestApi = zod.object({
    interviewee_identifier: zod
        .string()
        .max(previewInviteRequestApiIntervieweeIdentifierMax)
        .optional()
        .describe(
            'Which targeted interviewee to render the preview for (an email or PostHog distinct ID already on the topic). Leave blank to preview for the first targeted interviewee.'
        ),
})

export type PreviewInviteRequestApi = zod.input<typeof PreviewInviteRequestApi>
export type PreviewInviteRequestApiOutput = zod.output<typeof PreviewInviteRequestApi>

export const PreviewInviteResultApi = zod.object({
    interviewee_identifier: zod
        .string()
        .describe('The identifier (email or distinct ID) the preview was rendered for.'),
    user_name: zod.string().describe('The display name used in the email greeting, derived from the identifier.'),
    email: zod
        .email()
        .nullable()
        .describe('The email address the invite would be sent to. Null for distinct-ID-only interviewees.'),
    subject: zod.string().describe('The rendered subject line (saved topic subject, sanitized, or the default).'),
    html: zod
        .string()
        .describe(
            'The fully rendered, CSS-inlined HTML body of the invite email. Safe to display in a sandboxed iframe.'
        ),
    interview_url: zod
        .url()
        .describe(
            'An illustrative placeholder interview link shown in the previewed email body. The preview never exposes a real per-recipient share token — that link is minted only when invites are sent.'
        ),
    emailable: zod
        .boolean()
        .describe('True if this interviewee has an email address and could actually receive the invite.'),
    is_preview_link: zod
        .boolean()
        .describe('Always true — the previewed interview_url is an illustrative placeholder, never a live link.'),
})

export type PreviewInviteResultApi = zod.input<typeof PreviewInviteResultApi>
export type PreviewInviteResultApiOutput = zod.output<typeof PreviewInviteResultApi>

export const sendInvitesRequestApiSubjectMax = 200

export const sendInvitesRequestApiSendAsyncDefault = true

export const SendInvitesRequestApi = zod.object({
    subject: zod
        .string()
        .max(sendInvitesRequestApiSubjectMax)
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
        .default(sendInvitesRequestApiSendAsyncDefault)
        .describe(
            'If true (default), queue delivery via Celery. If false, send synchronously and surface errors immediately.'
        ),
})

export type SendInvitesRequestApi = zod.input<typeof SendInvitesRequestApi>
export type SendInvitesRequestApiOutput = zod.output<typeof SendInvitesRequestApi>

export const InterviewInviteResultApi = zod.object({
    interviewee_identifier: zod
        .string()
        .describe('The original identifier (email or distinct ID) from the topic targeting.'),
    email: zod
        .email()
        .nullish()
        .describe('Email used for delivery. Null when the identifier was not an email (e.g., a distinct ID).'),
    interview_url: zod.url().describe('The personalized public interview URL embedded in the email body.'),
    sent: zod
        .boolean()
        .describe('True if an email was queued for delivery. False when the recipient was skipped — see `reason`.'),
    reason: zod
        .string()
        .optional()
        .describe(
            'Why the email was skipped (e.g., `not_an_email`, `duplicate_recipient`, `already_sent`). Empty when sent=true.'
        ),
})

export type InterviewInviteResultApi = zod.input<typeof InterviewInviteResultApi>
export type InterviewInviteResultApiOutput = zod.output<typeof InterviewInviteResultApi>

export const PaginatedInterviewInviteResultListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(InterviewInviteResultApi),
})

export type PaginatedInterviewInviteResultListApi = zod.input<typeof PaginatedInterviewInviteResultListApi>
export type PaginatedInterviewInviteResultListApiOutput = zod.output<typeof PaginatedInterviewInviteResultListApi>

export const SharedInterviewLinkApi = zod.object({
    interview_url: zod
        .url()
        .describe(
            'Public, unauthenticated URL any respondent can open to start a new interview for this topic. Backed by a topic-level SharingConfiguration access token — not tied to any specific interviewee. Each visit is a new anonymous respondent who self-identifies with a name; `distinct_id` and `session_id` query params on the URL are captured as best-effort person\/session linkage.'
        ),
})

export type SharedInterviewLinkApi = zod.input<typeof SharedInterviewLinkApi>
export type SharedInterviewLinkApiOutput = zod.output<typeof SharedInterviewLinkApi>

export const LatestTestInterviewApi = zod.object({
    completed_at: zod.iso.datetime({ offset: true }).describe('When the test interview was completed.'),
    transcript: zod.string().describe('Full transcript of the test call, if Vapi delivered one. May be empty.'),
    summary: zod.string().describe('AI-generated summary of the test call, if Vapi delivered one. May be empty.'),
})

export type LatestTestInterviewApi = zod.input<typeof LatestTestInterviewApi>
export type LatestTestInterviewApiOutput = zod.output<typeof LatestTestInterviewApi>

export const TestInterviewLinkApi = zod.object({
    interview_url: zod
        .url()
        .describe(
            'Public, unauthenticated URL the topic author opens to dogfood the voice interview themselves — does not count against the targeted interviewees.'
        ),
    latest_test_interview: zod
        .union([LatestTestInterviewApi, zod.null()])
        .describe('Most recent test interview completed by the topic author, or null if none yet.'),
})

export type TestInterviewLinkApi = zod.input<typeof TestInterviewLinkApi>
export type TestInterviewLinkApiOutput = zod.output<typeof TestInterviewLinkApi>

export const intervieweeContextApiIntervieweeIdentifierMax = 400

export const intervieweeContextApiAgentContextMax = 10000

export const IntervieweeContextApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    interviewee_identifier: zod
        .string()
        .max(intervieweeContextApiIntervieweeIdentifierMax)
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(intervieweeContextApiAgentContextMax)
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

export type IntervieweeContextApi = zod.input<typeof IntervieweeContextApi>
export type IntervieweeContextApiOutput = zod.output<typeof IntervieweeContextApi>

export const PaginatedIntervieweeContextListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(IntervieweeContextApi),
})

export type PaginatedIntervieweeContextListApi = zod.input<typeof PaginatedIntervieweeContextListApi>
export type PaginatedIntervieweeContextListApiOutput = zod.output<typeof PaginatedIntervieweeContextListApi>

export const patchedIntervieweeContextApiIntervieweeIdentifierMax = 400

export const patchedIntervieweeContextApiAgentContextMax = 10000

export const PatchedIntervieweeContextApi = zod.object({
    id: zod.uuid().optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    interviewee_identifier: zod
        .string()
        .max(patchedIntervieweeContextApiIntervieweeIdentifierMax)
        .optional()
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(patchedIntervieweeContextApiAgentContextMax)
        .optional()
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

export type PatchedIntervieweeContextApi = zod.input<typeof PatchedIntervieweeContextApi>
export type PatchedIntervieweeContextApiOutput = zod.output<typeof PatchedIntervieweeContextApi>

export const bulkIntervieweeContextItemApiIntervieweeIdentifierMax = 400

export const bulkIntervieweeContextItemApiAgentContextMax = 10000

export const BulkIntervieweeContextItemApi = zod.object({
    interviewee_identifier: zod
        .string()
        .max(bulkIntervieweeContextItemApiIntervieweeIdentifierMax)
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(bulkIntervieweeContextItemApiAgentContextMax)
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

export type BulkIntervieweeContextItemApi = zod.input<typeof BulkIntervieweeContextItemApi>
export type BulkIntervieweeContextItemApiOutput = zod.output<typeof BulkIntervieweeContextItemApi>

export const BulkIntervieweeContextRequestApi = zod.object({
    items: zod
        .array(BulkIntervieweeContextItemApi)
        .describe(
            'List of interviewee context rows to create. Each item has an `interviewee_identifier` and an `agent_context`. At most 500 items per request.'
        ),
})

export type BulkIntervieweeContextRequestApi = zod.input<typeof BulkIntervieweeContextRequestApi>
export type BulkIntervieweeContextRequestApiOutput = zod.output<typeof BulkIntervieweeContextRequestApi>

export const BulkIntervieweeContextResponseApi = zod.object({
    inserted_count: zod.number().describe('Number of rows inserted by this request.'),
    skipped_count: zod
        .number()
        .describe('Number of items skipped because a row for that (topic, interviewee_identifier) already existed.'),
    skipped_identifiers: zod
        .array(zod.string())
        .describe(
            'Identifiers from the request whose rows were skipped because a row for that (topic, interviewee_identifier) already existed.'
        ),
})

export type BulkIntervieweeContextResponseApi = zod.input<typeof BulkIntervieweeContextResponseApi>
export type BulkIntervieweeContextResponseApiOutput = zod.output<typeof BulkIntervieweeContextResponseApi>

export const ClassificationsEnumApi = zod
    .enum(['abandoned', 'off-topic'])
    .describe('\* `abandoned` - Abandoned\n\* `off-topic` - Off-topic')

export type ClassificationsEnumApi = zod.input<typeof ClassificationsEnumApi>
export type ClassificationsEnumApiOutput = zod.output<typeof ClassificationsEnumApi>

export const userInterviewApiIntervieweeEmailsItemMax = 254

export const UserInterviewApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    interviewee_emails: zod.array(zod.string().max(userInterviewApiIntervieweeEmailsItemMax)).optional(),
    interviewee_identifier: zod.string(),
    topic: zod.uuid().nullable(),
    transcript: zod.string(),
    summary: zod.string().optional(),
    classifications: zod
        .array(ClassificationsEnumApi)
        .optional()
        .describe(
            'Searchable classifications on the response. `abandoned` is auto-derived from the transcript when the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update replaces the whole list — pass the full desired set, not a delta.'
        ),
    audio: zod.url(),
})

export type UserInterviewApi = zod.input<typeof UserInterviewApi>
export type UserInterviewApiOutput = zod.output<typeof UserInterviewApi>

export const PaginatedUserInterviewListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(UserInterviewApi),
})

export type PaginatedUserInterviewListApi = zod.input<typeof PaginatedUserInterviewListApi>
export type PaginatedUserInterviewListApiOutput = zod.output<typeof PaginatedUserInterviewListApi>

export const patchedUserInterviewApiIntervieweeEmailsItemMax = 254

export const PatchedUserInterviewApi = zod.object({
    id: zod.uuid().optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    interviewee_emails: zod.array(zod.string().max(patchedUserInterviewApiIntervieweeEmailsItemMax)).optional(),
    interviewee_identifier: zod.string().optional(),
    topic: zod.uuid().nullish(),
    transcript: zod.string().optional(),
    summary: zod.string().optional(),
    classifications: zod
        .array(ClassificationsEnumApi)
        .optional()
        .describe(
            'Searchable classifications on the response. `abandoned` is auto-derived from the transcript when the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update replaces the whole list — pass the full desired set, not a delta.'
        ),
    audio: zod.url().optional(),
})

export type PatchedUserInterviewApi = zod.input<typeof PatchedUserInterviewApi>
export type PatchedUserInterviewApiOutput = zod.output<typeof PatchedUserInterviewApi>

export const UserInterviewSearchDocumentTypeEnumApi = zod
    .enum(['transcript', 'summary'])
    .describe('\* `transcript` - transcript\n\* `summary` - summary')

export type UserInterviewSearchDocumentTypeEnumApi = zod.input<typeof UserInterviewSearchDocumentTypeEnumApi>
export type UserInterviewSearchDocumentTypeEnumApiOutput = zod.output<typeof UserInterviewSearchDocumentTypeEnumApi>

export const userInterviewSearchRequestApiQueryMax = 2000

export const userInterviewSearchRequestApiLimitMax = 50

export const UserInterviewSearchRequestApi = zod.object({
    query: zod
        .string()
        .max(userInterviewSearchRequestApiQueryMax)
        .describe('Natural-language query to match semantically against interview transcripts and summaries.'),
    document_types: zod
        .array(UserInterviewSearchDocumentTypeEnumApi)
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
        .array(ClassificationsEnumApi)
        .min(1)
        .optional()
        .describe(
            'Optional. Restrict results to interviews carrying any of these classifications (OR). Combines with `topic_id` as AND.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(userInterviewSearchRequestApiLimitMax)
        .optional()
        .describe(
            'Maximum number of matches to return (1-50). Defaults to 10. Two matches per interview are possible — one for the transcript, one for the summary.'
        ),
})

export type UserInterviewSearchRequestApi = zod.input<typeof UserInterviewSearchRequestApi>
export type UserInterviewSearchRequestApiOutput = zod.output<typeof UserInterviewSearchRequestApi>

export const UserInterviewSearchResultApi = zod.object({
    interview_id: zod.uuid().describe('ID of the matched UserInterview.'),
    document_type: UserInterviewSearchDocumentTypeEnumApi.describe(
        'Which document type matched — `transcript` is the raw conversation, `summary` is the AI-generated abstract.\n\n\* `transcript` - transcript\n\* `summary` - summary'
    ),
    similarity: zod
        .number()
        .describe('Cosine similarity in [0, 1]; higher is closer to the query. Computed as `1 - cosineDistance`.'),
    content_snippet: zod.string().describe('Excerpt of the matched document (first 500 characters).'),
    interviewee_identifier: zod.string().describe('Email or PostHog distinct ID of the interviewee.'),
    topic_id: zod
        .uuid()
        .nullable()
        .describe('ID of the UserInterviewTopic the interview was conducted for, or null if detached.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the interview row was created.'),
})

export type UserInterviewSearchResultApi = zod.input<typeof UserInterviewSearchResultApi>
export type UserInterviewSearchResultApiOutput = zod.output<typeof UserInterviewSearchResultApi>
