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
 * * `email` - Email
 * * `survey` - Survey
 * * `event` - Event
 * * `cohort` - Cohort
 * * `session` - Session
 */
export type TouchChannelEnumApi = (typeof TouchChannelEnumApi)[keyof typeof TouchChannelEnumApi]

export const TouchChannelEnumApi = {
    Email: 'email',
    Survey: 'survey',
    Event: 'event',
    Cohort: 'cohort',
    Session: 'session',
} as const

export interface ResearchTouchApi {
    /** How the contact was reached: email, survey, event, cohort, or session.
     *
     * * `email` - Email
     * * `survey` - Survey
     * * `event` - Event
     * * `cohort` - Cohort
     * * `session` - Session */
    channel: TouchChannelEnumApi
    /** Email address that was contacted. */
    contact: string
    /** Name of the source or session that made the contact. */
    source_label: string
    /** Employee responsible for the contact, if known. */
    owner_email: string
    /**
     * When the contact happened. Empty for cohort membership.
     * @nullable
     */
    occurred_at: string | null
    /**
     * ID of the source that made the contact, if any.
     * @nullable
     */
    source_id?: string | null
    /**
     * ID of the session, for session touches.
     * @nullable
     */
    session_id?: string | null
}

export interface ContactCheckResultApi {
    /** Every research touch found, newest first. */
    touches: ResearchTouchApi[]
    /** Normalized emails that were checked. */
    emails: string[]
    /**
     * Normalized domain that was checked, if any.
     * @nullable
     */
    domain: string | null
    /**
     * Most recent dated touch, if any.
     * @nullable
     */
    last_touch_at: string | null
    /** True when a touch falls inside the warning window or the contact is in an active 'already contacted' cohort. This is a warning, not a block. */
    recently_contacted: boolean
    /** Size of the warning window in days. */
    warn_within_days: number
    /** How far back touches were searched, in days. */
    lookback_days: number
}

/**
 * * `calendar` - Calendar
 * * `manual` - Manual
 */
export type SessionOriginEnumApi = (typeof SessionOriginEnumApi)[keyof typeof SessionOriginEnumApi]

export const SessionOriginEnumApi = {
    Calendar: 'calendar',
    Manual: 'manual',
} as const

/**
 * * `scheduled` - Scheduled
 * * `held` - Held
 * * `cancelled` - Cancelled
 */
export type SessionStatusEnumApi = (typeof SessionStatusEnumApi)[keyof typeof SessionStatusEnumApi]

export const SessionStatusEnumApi = {
    Scheduled: 'scheduled',
    Held: 'held',
    Cancelled: 'cancelled',
} as const

export interface ResearchSessionDTOApi {
    /** Unique ID of the session. */
    id: string
    /** Where the session was detected, such as a calendar.
     *
     * * `calendar` - Calendar
     * * `manual` - Manual */
    origin: SessionOriginEnumApi
    /** Stable ID from the origin, such as a calendar event UID. */
    external_ref: string
    /** Meeting title. */
    title: string
    /** When the session starts. */
    start_time: string
    /**
     * When the session ends, if known.
     * @nullable
     */
    end_time: string | null
    /** Scheduled, held, or cancelled.
     *
     * * `scheduled` - Scheduled
     * * `held` - Held
     * * `cancelled` - Cancelled */
    status: SessionStatusEnumApi
    /** Email of the employee who organized the session. */
    organizer_email: string
    /** PostHog attendees. */
    internal_emails: string[]
    /** Customer attendees. */
    external_emails: string[]
    /** Link to join the meeting, if known. */
    meeting_url: string
    /**
     * When a brief for this session was posted to Slack.
     * @nullable
     */
    brief_posted_at: string | null
    /** When the session was first detected. */
    created_at: string
}

/**
 * * `workflow` - Workflow
 * * `survey` - Survey
 * * `cohort` - Cohort
 * * `event` - Event
 */
export type SourceKindEnumApi = (typeof SourceKindEnumApi)[keyof typeof SourceKindEnumApi]

export const SourceKindEnumApi = {
    Workflow: 'workflow',
    Survey: 'survey',
    Cohort: 'cohort',
    Event: 'event',
} as const

/**
 * * `manual` - Manual
 * * `scout` - Scout
 */
export type ResearchSourceDTOOriginEnumApi =
    (typeof ResearchSourceDTOOriginEnumApi)[keyof typeof ResearchSourceDTOOriginEnumApi]

export const ResearchSourceDTOOriginEnumApi = {
    Manual: 'manual',
    Scout: 'scout',
} as const

export interface ResearchSourceDTOApi {
    /** Unique ID of the source. */
    id: string
    /** What the source is: a workflow, survey, cohort, or event name.
     *
     * * `workflow` - Workflow
     * * `survey` - Survey
     * * `cohort` - Cohort
     * * `event` - Event */
    kind: SourceKindEnumApi
    /** Workflow ID, survey ID, cohort ID, or event name that identifies the source. */
    external_id: string
    /** Human-readable name, such as 'Error tracking interview outreach'. */
    label: string
    /** Email of the PostHog employee who runs this outreach. */
    owner_email: string
    /** Product area the outreach is about, such as 'session replay'. */
    product_area: string
    /** Whether a person or a scout registered the source.
     *
     * * `manual` - Manual
     * * `scout` - Scout */
    origin: ResearchSourceDTOOriginEnumApi
    /** Inactive sources are ignored by the contact check. */
    active: boolean
    /** When the source was registered. */
    created_at: string
    /** When the source was last changed. */
    updated_at: string
}

export interface CreateResearchSourceApi {
    /** What the source is: a workflow, survey, cohort, or event name.
     *
     * * `workflow` - Workflow
     * * `survey` - Survey
     * * `cohort` - Cohort
     * * `event` - Event */
    kind: SourceKindEnumApi
    /**
     * Workflow ID, survey ID, cohort ID, or event name, depending on kind.
     * @maxLength 400
     */
    external_id: string
    /**
     * Human-readable name for the source.
     * @maxLength 255
     */
    label: string
    /** Email of the employee who runs this outreach. */
    owner_email?: string
    /**
     * Product area the outreach is about.
     * @maxLength 128
     */
    product_area?: string
}

export interface PatchedUpdateResearchSourceApi {
    /**
     * Human-readable name for the source.
     * @maxLength 255
     */
    label?: string
    /** Email of the employee who runs this outreach. */
    owner_email?: string
    /**
     * Product area the outreach is about.
     * @maxLength 128
     */
    product_area?: string
    /** Set to false to stop counting this source. */
    active?: boolean
}

export type ResearchDeskContactCheckListParams = {
    /**
     * Company domain to check, such as 'example.com'. Matches anyone at that domain.
     * @maxLength 253
     */
    domain?: string
    /**
     * Emails to check. Repeat the parameter or pass a comma-separated list.
     * @maxItems 50
     * @items.maxLength 320
     */
    emails?: string[]
    /**
     * How far back to search, in days.
     * @minimum 1
     * @maximum 730
     */
    lookback_days?: number
    /**
     * Touches within this many days set recently_contacted.
     * @minimum 0
     * @maximum 730
     */
    warn_within_days?: number
}

export type ResearchDeskSessionsListParams = {
    /**
     * Only return sessions that start at or after this time (ISO 8601).
     */
    start_after?: string
    /**
     * Only return sessions that start before this time (ISO 8601).
     */
    start_before?: string
}
