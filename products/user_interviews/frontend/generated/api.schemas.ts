/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface UserInterviewTopicApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /**
     * Email addresses of people to interview. May be combined with interviewee_distinct_ids.
     * @items.maxLength 254
     */
    interviewee_emails?: string[]
    /**
     * PostHog distinct IDs of people to interview. May be combined with interviewee_emails.
     * @items.maxLength 400
     */
    interviewee_distinct_ids?: string[]
    /** The product, feature, or idea you want to ask interviewees about. */
    topic: string
    /** Optional additional system prompt for the voice agent — extra background, tone, or constraints. */
    agent_context?: string
    /** Ordered list of questions the voice agent should work through during the interview. */
    questions?: string[]
    /**
     * Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.
     * @maxLength 255
     */
    invite_subject?: string
    /**
     * Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.
     * @maxLength 1000
     */
    invite_message?: string
}

export interface PaginatedUserInterviewTopicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserInterviewTopicApi[]
}

export interface PatchedUserInterviewTopicApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /**
     * Email addresses of people to interview. May be combined with interviewee_distinct_ids.
     * @items.maxLength 254
     */
    interviewee_emails?: string[]
    /**
     * PostHog distinct IDs of people to interview. May be combined with interviewee_emails.
     * @items.maxLength 400
     */
    interviewee_distinct_ids?: string[]
    /** The product, feature, or idea you want to ask interviewees about. */
    topic?: string
    /** Optional additional system prompt for the voice agent — extra background, tone, or constraints. */
    agent_context?: string
    /** Ordered list of questions the voice agent should work through during the interview. */
    questions?: string[]
    /**
     * Subject line for the invitation email. Plain text only — URLs, angle brackets, and control characters are rejected. Leave blank to use the default subject. Personalization is handled by the email template, so do not include placeholders.
     * @maxLength 255
     */
    invite_subject?: string
    /**
     * Intro message shown in the invitation email body, above the interview link. Plain prose only — URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank to use the default copy.
     * @maxLength 1000
     */
    invite_message?: string
}

export interface IntervieweeIdentifierRequestApi {
    /**
     * Email address or PostHog distinct ID for the interviewee. Email-shaped values (including the `Display Name <email@host>` form) are routed to `interviewee_emails`; everything else lands in `interviewee_distinct_ids`.
     * @maxLength 400
     */
    identifier: string
}

export interface InterviewLinkApi {
    /**
     * The original identifier (email or distinct ID) from the topic targeting.
     * @maxLength 400
     */
    interviewee_identifier: string
    /** Best-effort display name derived from the identifier, used to greet the interviewee. */
    user_name: string
    /** Public, unauthenticated URL the interviewee opens to start the call. Backed by a SharingConfiguration access token. */
    interview_url: string
    /** The merged topic + per-interviewee context the voice agent will see during the call. */
    agent_context: string
}

export interface PaginatedInterviewLinkListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: InterviewLinkApi[]
}

export interface PreviewInviteRequestApi {
    /**
     * Which targeted interviewee to render the preview for (an email or PostHog distinct ID already on the topic). Leave blank to preview for the first targeted interviewee.
     * @maxLength 400
     */
    interviewee_identifier?: string
}

export interface PreviewInviteResultApi {
    /** The identifier (email or distinct ID) the preview was rendered for. */
    interviewee_identifier: string
    /** The display name used in the email greeting, derived from the identifier. */
    user_name: string
    /**
     * The email address the invite would be sent to. Null for distinct-ID-only interviewees.
     * @nullable
     */
    email: string | null
    /** The rendered subject line (saved topic subject, sanitized, or the default). */
    subject: string
    /** The fully rendered, CSS-inlined HTML body of the invite email. Safe to display in a sandboxed iframe. */
    html: string
    /** An illustrative placeholder interview link shown in the previewed email body. The preview never exposes a real per-recipient share token — that link is minted only when invites are sent. */
    interview_url: string
    /** True if this interviewee has an email address and could actually receive the invite. */
    emailable: boolean
    /** Always true — the previewed interview_url is an illustrative placeholder, never a live link. */
    is_preview_link: boolean
}

export interface SendInvitesRequestApi {
    /**
     * Override the email subject line for this send. Plain text only — URLs, angle brackets, and control characters are rejected. Falls back to the topic's saved subject, then a default.
     * @maxLength 200
     */
    subject?: string
    /** Email address replies should go to. Defaults to the topic creator's email if blank. */
    reply_to?: string
    /** If true (default), queue delivery via Celery. If false, send synchronously and surface errors immediately. */
    send_async?: boolean
}

export interface InterviewInviteResultApi {
    /** The original identifier (email or distinct ID) from the topic targeting. */
    interviewee_identifier: string
    /**
     * Email used for delivery. Null when the identifier was not an email (e.g., a distinct ID).
     * @nullable
     */
    email?: string | null
    /** The personalized public interview URL embedded in the email body. */
    interview_url: string
    /** True if an email was queued for delivery. False when the recipient was skipped — see `reason`. */
    sent: boolean
    /** Why the email was skipped (e.g., `not_an_email`, `duplicate_recipient`, `already_sent`). Empty when sent=true. */
    reason?: string
}

export interface PaginatedInterviewInviteResultListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: InterviewInviteResultApi[]
}

export interface LatestTestInterviewApi {
    /** When the test interview was completed. */
    completed_at: string
    /** Full transcript of the test call, if Vapi delivered one. May be empty. */
    transcript: string
    /** AI-generated summary of the test call, if Vapi delivered one. May be empty. */
    summary: string
}

export interface TestInterviewLinkApi {
    /** Public, unauthenticated URL the topic author opens to dogfood the voice interview themselves — does not count against the targeted interviewees. */
    interview_url: string
    /** Most recent test interview completed by the topic author, or null if none yet. */
    latest_test_interview: LatestTestInterviewApi | null
}

export interface IntervieweeContextApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /**
     * Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.
     * @maxLength 400
     */
    interviewee_identifier: string
    /**
     * Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.
     * @maxLength 10000
     */
    agent_context: string
}

export interface PaginatedIntervieweeContextListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IntervieweeContextApi[]
}

export interface PatchedIntervieweeContextApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /**
     * Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.
     * @maxLength 400
     */
    interviewee_identifier?: string
    /**
     * Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.
     * @maxLength 10000
     */
    agent_context?: string
}

export interface BulkIntervieweeContextItemApi {
    /**
     * Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.
     * @maxLength 400
     */
    interviewee_identifier: string
    /**
     * Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.
     * @maxLength 10000
     */
    agent_context: string
}

export interface BulkIntervieweeContextRequestApi {
    /** List of interviewee context rows to create. Each item has an `interviewee_identifier` and an `agent_context`. At most 500 items per request. */
    items: BulkIntervieweeContextItemApi[]
}

export interface BulkIntervieweeContextResponseApi {
    /** Number of rows inserted by this request. */
    inserted_count: number
    /** Number of items skipped because a row for that (topic, interviewee_identifier) already existed. */
    skipped_count: number
    /** Identifiers from the request whose rows were skipped because a row for that (topic, interviewee_identifier) already existed. */
    skipped_identifiers: string[]
}

/**
 * * `abandoned` - Abandoned
 * * `off-topic` - Off-topic
 */
export type ClassificationsEnumApi = (typeof ClassificationsEnumApi)[keyof typeof ClassificationsEnumApi]

export const ClassificationsEnumApi = {
    Abandoned: 'abandoned',
    OffTopic: 'off-topic',
} as const

export interface UserInterviewApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @items.maxLength 254 */
    interviewee_emails?: string[]
    readonly interviewee_identifier: string
    /** @nullable */
    readonly topic: string | null
    readonly transcript: string
    summary?: string
    /** Searchable classifications on the response. `abandoned` is auto-derived from the transcript when the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update replaces the whole list — pass the full desired set, not a delta. */
    classifications?: ClassificationsEnumApi[]
    audio: string
}

export interface PaginatedUserInterviewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserInterviewApi[]
}

export interface PatchedUserInterviewApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @items.maxLength 254 */
    interviewee_emails?: string[]
    readonly interviewee_identifier?: string
    /** @nullable */
    readonly topic?: string | null
    readonly transcript?: string
    summary?: string
    /** Searchable classifications on the response. `abandoned` is auto-derived from the transcript when the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update replaces the whole list — pass the full desired set, not a delta. */
    classifications?: ClassificationsEnumApi[]
    audio?: string
}

/**
 * * `transcript` - transcript
 * * `summary` - summary
 */
export type UserInterviewSearchDocumentTypeEnumApi =
    (typeof UserInterviewSearchDocumentTypeEnumApi)[keyof typeof UserInterviewSearchDocumentTypeEnumApi]

export const UserInterviewSearchDocumentTypeEnumApi = {
    Transcript: 'transcript',
    Summary: 'summary',
} as const

export interface UserInterviewSearchRequestApi {
    /**
     * Natural-language query to match semantically against interview transcripts and summaries.
     * @maxLength 2000
     */
    query: string
    /**
     * Which document types to search across. Omit to default to both `transcript` and `summary`. Pass a non-empty subset to restrict the search.
     * @minItems 1
     */
    document_types?: UserInterviewSearchDocumentTypeEnumApi[]
    /**
     * Optional. Restrict results to interviews belonging to a specific UserInterviewTopic.
     * @nullable
     */
    topic_id?: string | null
    /**
     * Optional. Restrict results to interviews carrying any of these classifications (OR). Combines with `topic_id` as AND.
     * @minItems 1
     */
    classifications?: ClassificationsEnumApi[]
    /**
     * Maximum number of matches to return (1-50). Defaults to 10. Two matches per interview are possible — one for the transcript, one for the summary.
     * @minimum 1
     * @maximum 50
     */
    limit?: number
}

export interface UserInterviewSearchResultApi {
    /** ID of the matched UserInterview. */
    interview_id: string
    /** Which document type matched — `transcript` is the raw conversation, `summary` is the AI-generated abstract.
     *
     * * `transcript` - transcript
     * * `summary` - summary */
    document_type: UserInterviewSearchDocumentTypeEnumApi
    /** Cosine similarity in [0, 1]; higher is closer to the query. Computed as `1 - cosineDistance`. */
    similarity: number
    /** Excerpt of the matched document (first 500 characters). */
    content_snippet: string
    /** Email or PostHog distinct ID of the interviewee. */
    interviewee_identifier: string
    /**
     * ID of the UserInterviewTopic the interview was conducted for, or null if detached.
     * @nullable
     */
    topic_id: string | null
    /** When the interview row was created. */
    created_at: string
}

export type UserInterviewTopicsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type UserInterviewTopicsIntervieweesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UserInterviewsListParams = {
    /**
     * Comma-separated classifications; returns responses carrying any of them (OR). Valid values: abandoned, off-topic.
     */
    classifications?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    topic?: string
}
