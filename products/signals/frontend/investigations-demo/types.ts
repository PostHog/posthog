/**
 * Demo-only types for the investigations inbox redesign preview.
 * Everything on these pages is mock data; nothing talks to the backend.
 */

export type InvestigationState =
    | 'worsening'
    | 'recovering'
    | 'holding'
    | 'measuring'
    | 'resolved'
    | 'disputed'
    | 'dismissed'

export type InvestigationStatus =
    | 'New'
    | 'Investigating'
    | 'Assigned'
    | 'Viewed'
    | 'Verifying'
    | 'Resolved'
    | 'Disputed'
    | 'Dismissed'

export type InvestigationTrend = 'up' | 'down' | 'flat'

export interface InvestigationStorySection {
    label: string
    body: string
    code?: string
}

/** Extra content for investigations that appear in focus mode. */
export interface InvestigationFocusContent {
    /** e.g. "detected 18h ago" or "fix shipped 8h ago" */
    age: string
    /** Trend annotation without the glyph, e.g. "growing ~600/wk" */
    trendLabel: string
    /** Primary action label, e.g. "Fix & monitor" or "Pause variant B" */
    actionLabel: string
    /** Feature flag key created with the fix PR, when the action is "Fix & monitor" */
    flagKey?: string
    /** Toast shown after the primary action runs */
    fixToast: string
    story: InvestigationStorySection[]
}

export interface DemoInvestigation {
    id: string
    headline: string
    /** Mono area tag, e.g. "CHECKOUT" or "MOBILE · UPLOADS" */
    area: string
    /** Headline impact figure, e.g. "1,847 users" or "p95 +740ms" */
    impact: string
    trend: InvestigationTrend
    /** Sort weight for the impact sort, higher = more impact */
    impactWeight: number
    /** Age in hours for the recency sort */
    ageHours: number
    /** Display creation time, e.g. "Aug 17, 16:12" */
    created: string
    status: InvestigationStatus
    state: InvestigationState
    unread?: boolean
    /** True while the engine is still investigating (rotating activity phrase + shimmer) */
    live?: boolean
    /** One-paragraph verdict shown in the row preview and focus card */
    verdict: string
    /** Mono proof line, e.g. "214 session replays · 6 tickets" */
    proof: string
    /** Whether the row links through to the full demo report */
    hasReport: boolean
    focus?: InvestigationFocusContent
}

/** Fix lifecycle phases on the full report page. */
export type ReportFixPhase = 'reported' | 'generating' | 'proposed' | 'sent' | 'committed' | 'launched'

export type InboxDemoFilter = 'all' | 'attention' | 'open' | 'monitoring' | 'archived'
export type InboxDemoSort = 'impact' | 'recency'

/** Status a focus-mode action stamps on an investigation. */
export type FocusActedStatus = 'Acknowledged' | 'Dismissed' | 'In progress'
