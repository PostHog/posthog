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
 * * `user` - User
 * * `hog` - Hog
 * * `system` - System
 */
export type HogMessageAuthorEnumApi = (typeof HogMessageAuthorEnumApi)[keyof typeof HogMessageAuthorEnumApi]

export const HogMessageAuthorEnumApi = {
    User: 'user',
    Hog: 'hog',
    System: 'system',
} as const

/**
 * * `p0` - P0
 * * `p1` - P1
 * * `p2` - P2
 * * `p3` - P3
 * * `p4` - P4
 */
export type HogReportPriorityEnumApi = (typeof HogReportPriorityEnumApi)[keyof typeof HogReportPriorityEnumApi]

export const HogReportPriorityEnumApi = {
    P0: 'p0',
    P1: 'p1',
    P2: 'p2',
    P3: 'p3',
    P4: 'p4',
} as const

/**
 * * `insight` - Insight
 * * `event` - Event
 * * `error` - Error
 * * `replay` - Replay
 * * `flag` - Flag
 * * `experiment` - Experiment
 * * `survey` - Survey
 * * `log` - Log
 * * `ticket` - Ticket
 * * `message` - Message
 * * `code` - Code
 * * `other` - Other
 */
export type HogEvidenceKindEnumApi = (typeof HogEvidenceKindEnumApi)[keyof typeof HogEvidenceKindEnumApi]

export const HogEvidenceKindEnumApi = {
    Insight: 'insight',
    Event: 'event',
    Error: 'error',
    Replay: 'replay',
    Flag: 'flag',
    Experiment: 'experiment',
    Survey: 'survey',
    Log: 'log',
    Ticket: 'ticket',
    Message: 'message',
    Code: 'code',
    Other: 'other',
} as const

export interface HogEvidenceDTOApi {
    description: string
    source: string
    kind?: HogEvidenceKindEnumApi
}

/**
 * * `open` - Open
 * * `resolved` - Resolved
 * * `dismissed` - Dismissed
 */
export type HogReportStatusEnumApi = (typeof HogReportStatusEnumApi)[keyof typeof HogReportStatusEnumApi]

export const HogReportStatusEnumApi = {
    Open: 'open',
    Resolved: 'resolved',
    Dismissed: 'dismissed',
} as const

/**
 * * `implement` - Implement
 * * `investigate` - Investigate
 */
export type HogReportFollowUpEnumApi = (typeof HogReportFollowUpEnumApi)[keyof typeof HogReportFollowUpEnumApi]

export const HogReportFollowUpEnumApi = {
    Implement: 'implement',
    Investigate: 'investigate',
} as const

export interface HogReportDTOApi {
    id: string
    hog_id: string
    hog_name: string
    hog_emoji: string
    hog_color: string
    title: string
    summary: string
    priority: HogReportPriorityEnumApi
    impact: string
    proposal: string
    evidence: HogEvidenceDTOApi[]
    status: HogReportStatusEnumApi
    verdict_reason: string
    read: boolean
    created_at: string
    follow_up?: HogReportFollowUpEnumApi | null
}

/**
 * * `pending` - Pending
 * * `approved` - Approved
 * * `denied` - Denied
 * * `done` - Done
 */
export type HogActionStatusEnumApi = (typeof HogActionStatusEnumApi)[keyof typeof HogActionStatusEnumApi]

export const HogActionStatusEnumApi = {
    Pending: 'pending',
    Approved: 'approved',
    Denied: 'denied',
    Done: 'done',
} as const

export interface HogActionDTOApi {
    id: string
    hog_id: string
    hog_name: string
    hog_emoji: string
    hog_color: string
    kind: string
    label: string
    draft: string
    status: HogActionStatusEnumApi
    result: string
    created_at: string
    /** @nullable */
    decided_at?: string | null
}

export interface HogMessageDTOApi {
    id: string
    hog_id: string
    author: HogMessageAuthorEnumApi
    content: string
    in_chat: boolean
    created_at: string
    /** @nullable */
    from_hog_id?: string | null
    /** @nullable */
    from_hog_name?: string | null
    /** @nullable */
    delivered_at?: string | null
    /** @nullable */
    seen_at?: string | null
    /** @nullable */
    read_at?: string | null
    /** Set when the message is a report. The chat shows it as a card with its actions. */
    report?: HogReportDTOApi | null
    /** Set when the message asks the owner to approve an action. */
    action?: HogActionDTOApi | null
}

/**
 * * `setup` - Setup
 * * `active` - Active
 * * `paused` - Paused
 */
export type HogStatusEnumApi = (typeof HogStatusEnumApi)[keyof typeof HogStatusEnumApi]

export const HogStatusEnumApi = {
    Setup: 'setup',
    Active: 'active',
    Paused: 'paused',
} as const

export interface HogDTOApi {
    /** The newest message in the owner's chat with this hog. */
    last_message: HogMessageDTOApi | null
    id: string
    name: string
    emoji: string
    color: string
    /** The hog's charter. Blank until setup is done. */
    responsibility: string
    /** Notes the hog keeps for its future self. */
    memory: string
    status: HogStatusEnumApi
    /** MCP store installations this hog may use. */
    mcp_installation_ids: string[]
    /** True while the hog is acting on a wake. */
    working: boolean
    /** Messages from the hog that the owner has not opened. */
    unread_count: number
    /** Approvals that wait for the owner, plus open reports they have not acted on. Reading does not lower it. */
    needs_you_count: number
    created_at: string
}

export interface CreateHogApi {
    /**
     * The hog's display name.
     * @maxLength 80
     */
    name: string
    /**
     * Emoji shown as the avatar.
     * @maxLength 16
     */
    emoji?: string
    /**
     * Avatar background as a hex color.
     * @maxLength 16
     */
    color?: string
    /** What the hog looks after. Leave blank to let the hog ask for it in its first chat. */
    responsibility?: string
    /** IDs of the owner's MCP store installations this hog may use. */
    mcp_installation_ids?: string[]
}

export interface PatchedUpdateHogApi {
    /**
     * The hog's display name.
     * @maxLength 80
     */
    name?: string
    /**
     * Emoji shown as the avatar.
     * @maxLength 16
     */
    emoji?: string
    /**
     * Avatar background as a hex color.
     * @maxLength 16
     */
    color?: string
    /** The hog's charter: what it owns, what is worth reporting, and how often it checks. */
    responsibility?: string
    /**
     * Notes the hog keeps for its future self. Replaces the whole memory.
     * @maxLength 20000
     */
    memory?: string
    /** setup until the hog has a charter, then active. paused stops every wake.
     *
     * * `setup` - Setup
     * * `active` - Active
     * * `paused` - Paused */
    status?: HogStatusEnumApi
    /** IDs of the owner's MCP store installations this hog may use. */
    mcp_installation_ids?: string[]
}

/**
 * * `approve` - Approve
 * * `deny` - Deny
 */
export type HogActionDecisionEnumApi = (typeof HogActionDecisionEnumApi)[keyof typeof HogActionDecisionEnumApi]

export const HogActionDecisionEnumApi = {
    Approve: 'approve',
    Deny: 'deny',
} as const

export interface DecideActionApi {
    /** ID of the action. */
    action_id: string
    /** approve or deny.
     *
     * * `approve` - Approve
     * * `deny` - Deny */
    decision: HogActionDecisionEnumApi
    /** Also save the decision as a standing rule for this kind of action. */
    always?: boolean
    /**
     * An edited draft to approve in place of the hog's.
     * @maxLength 8000
     * @nullable
     */
    draft?: string | null
}

export interface CompleteActionApi {
    /** ID of the approved action you carried out. */
    action_id: string
    /**
     * What happened, with a link when there is one.
     * @maxLength 2000
     */
    result: string
}

export interface ProposeActionApi {
    /**
     * A short, stable name for the class of side effect, such as slack-message, github-pr or email-send. The owner's rules match on it, so reuse the same kind for the same sort of action.
     * @maxLength 60
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    kind: string
    /**
     * One line saying what you would do and to whom.
     * @maxLength 200
     */
    label: string
    /**
     * Exactly what you would send or change. The owner may edit it before approving.
     * @maxLength 8000
     */
    draft?: string
}

export interface EvidenceInputApi {
    /**
     * What this piece of evidence shows.
     * @maxLength 500
     */
    description: string
    /**
     * A link or an identifier a person can check, such as an insight URL or an issue ID.
     * @maxLength 1000
     */
    source: string
    /** What kind of record the source is.
     *
     * * `insight` - Insight
     * * `event` - Event
     * * `error` - Error
     * * `replay` - Replay
     * * `flag` - Flag
     * * `experiment` - Experiment
     * * `survey` - Survey
     * * `log` - Log
     * * `ticket` - Ticket
     * * `message` - Message
     * * `code` - Code
     * * `other` - Other */
    kind?: HogEvidenceKindEnumApi
}

export interface PublishReportApi {
    /**
     * The outcome to change, not the observation.
     * @maxLength 200
     */
    title: string
    /**
     * The first paragraph is the lead: what is happening, to whom, since when.
     * @maxLength 8000
     */
    summary: string
    /** p0 broken for many now, p1 hurts users today, p2 fix this week, p3 when there is time, p4 worth knowing.
     *
     * * `p0` - P0
     * * `p1` - P1
     * * `p2` - P2
     * * `p3` - P3
     * * `p4` - P4 */
    priority: HogReportPriorityEnumApi
    /**
     * One sentence that starts with the number that matters.
     * @maxLength 500
     */
    impact?: string
    /**
     * What you would do, concretely enough to act on.
     * @maxLength 4000
     */
    proposal?: string
    /**
     * Specific records a person can check.
     * @maxItems 20
     */
    evidence?: EvidenceInputApi[]
}

export interface ReportFollowUpApi {
    /** ID of the report. */
    report_id: string
    /** implement makes the proposed change. investigate finds the root cause and changes nothing.
     *
     * * `implement` - Implement
     * * `investigate` - Investigate */
    mode: HogReportFollowUpEnumApi
}

export interface ReportFollowUpResultApi {
    /** False when the hog is paused or at its hourly wake limit. */
    started: boolean
}

export interface ReportIdApi {
    /** ID of the report. */
    report_id: string
}

export interface ReportVerdictApi {
    /** ID of the report. */
    report_id: string
    /** resolved or dismissed closes the report. open reopens it.
     *
     * * `open` - Open
     * * `resolved` - Resolved
     * * `dismissed` - Dismissed */
    status: HogReportStatusEnumApi
    /**
     * Why, in a few words.
     * @maxLength 200
     */
    reason?: string
}

/**
 * * `allow` - Allow
 * * `ask` - Ask
 * * `deny` - Deny
 */
export type HogRuleEffectEnumApi = (typeof HogRuleEffectEnumApi)[keyof typeof HogRuleEffectEnumApi]

export const HogRuleEffectEnumApi = {
    Allow: 'allow',
    Ask: 'ask',
    Deny: 'deny',
} as const

export interface HogRuleDTOApi {
    id: string
    hog_id: string
    kind: string
    effect: HogRuleEffectEnumApi
}

export interface SetRuleApi {
    /**
     * The action kind the rule covers.
     * @maxLength 60
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    kind: string
    /** allow runs without asking, ask waits for the owner, deny refuses.
     *
     * * `allow` - Allow
     * * `ask` - Ask
     * * `deny` - Deny */
    effect: HogRuleEffectEnumApi
}

export interface MessageContentApi {
    /**
     * The message text.
     * @maxLength 8000
     */
    content: string
}

export interface HogScheduleDTOApi {
    id: string
    hog_id: string
    prompt: string
    /** @nullable */
    cron_expression: string | null
    /** @nullable */
    next_fire_at: string | null
    /** @nullable */
    last_fired_at: string | null
    enabled: boolean
    created_at: string
}

export interface CreateHogScheduleApi {
    /**
     * A note to your future self: what to check or do when this fires.
     * @maxLength 4000
     */
    prompt: string
    /**
     * Fire once at this ISO 8601 time.
     * @nullable
     */
    run_at?: string | null
    /**
     * Fire on a repeat: a 5-field cron expression in UTC, at most every 15 minutes.
     * @maxLength 120
     * @nullable
     */
    cron_expression?: string | null
}

export interface HogScheduleIdApi {
    /** ID of the schedule to delete. */
    schedule_id: string
}

export interface TellHogApi {
    /** ID of the hog to send the note to. Find it with hogs-list. */
    to_hog_id: string
    /**
     * The note. Say what you found and what you need.
     * @maxLength 8000
     */
    content: string
}

export interface HogTriggerDTOApi {
    id: string
    hog_id: string
    name: string
    instructions: string
    /** POST any JSON body to this path on the PostHog host to fire the trigger. */
    fire_path: string
    fire_count: number
    /** @nullable */
    last_fired_at: string | null
    created_at: string
}

export interface HogEventDTOApi {
    id: string
    trigger_id: string
    /** False for a repeated event, a paused hog, or a hog at its cap. */
    woke_hog: boolean
    created_at: string
}

export interface CreateHogTriggerApi {
    /**
     * What sends these events, such as Deploy finished.
     * @maxLength 120
     */
    name: string
    /**
     * A note to your future self: what to check when an event arrives, and what is worth reporting.
     * @maxLength 4000
     */
    instructions?: string
}

export interface HogTriggerIdApi {
    /** ID of the trigger to delete. */
    trigger_id: string
}

export type HogsMessagesRetrieveParams = {
    /**
     * Only return messages created after this ISO 8601 time.
     */
    after?: string
    /**
     * Also return notes between hogs, which the chat hides.
     */
    include_internal?: boolean
}

export type HogsTriggersFireCreateBodyOne = { [key: string]: unknown }

export type HogsTriggersFireCreateBodyTwo = { [key: string]: unknown }

export type HogsTriggersFireCreateBodyThree = { [key: string]: unknown }
