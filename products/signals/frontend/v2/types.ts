/**
 * Demo-only types for the inbox v2 redesign preview.
 * Everything on these pages is mock data; nothing talks to the backend.
 */

export type ReportStatus =
    | 'New'
    | 'Investigating'
    | 'Assigned'
    | 'Viewed'
    | 'Verifying'
    | 'Resolved'
    | 'Disputed'
    | 'Dismissed'

export type ReportTrend = 'up' | 'down' | 'flat'

export interface ReportStorySection {
    label: string
    body: string
    code?: string
}

/** Extra content for reports that appear in focus mode. */
export interface ReportFocusContent {
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
    story: ReportStorySection[]
}

export type DemoChartColor = 'accent' | 'muted' | 'success' | 'danger'

/** One line on a demo chart. Every series on a chart has the same number of points. */
export interface DemoChartSeries {
    name: string
    color: DemoChartColor
    points: number[]
    dashed?: boolean
    strokeWidth?: number
}

export interface DemoChartAnnotation {
    /** Index into the series points the vertical marker sits on */
    index: number
    label: string
    color: DemoChartColor
    /** Anchor the label to the left of the line instead of the right */
    labelAnchor?: 'start' | 'end'
}

export interface DemoChartData {
    series: DemoChartSeries[]
    /** Hover label per point, e.g. "Aug 18, 14:00" or "12h ago" */
    pointLabels: string[]
    /** Sparse axis labels spread evenly under the plot */
    xLabels: string[]
    /** Tooltip value suffix, e.g. "users" */
    unit?: string
    /** Horizontal dashed reference line, in data units */
    baselineValue?: number
    baselineLabel?: string
    annotations?: DemoChartAnnotation[]
}

/** Which micro-mock the evidence screenshot frame renders. */
export type DemoScreenshotKind = 'dashboard-tile' | 'usage-banner' | 'ai-error-card'

/** A mock screenshot of the error UI, drawn with tokens instead of an image asset. */
export interface DemoScreenshot {
    kind: DemoScreenshotKind
    /** Address-bar hint in the frame, e.g. "us.posthog.com/dashboard/214" */
    urlHint: string
    /** Where the frame was captured from, e.g. "session replay 018f-d3a2" */
    source: string
}

export interface ReportEvidenceCard {
    /** Micro label, e.g. "ERROR TRACKING" */
    label: string
    title: string
    detail: string
    /** Optional mini bar strip under the card body */
    bars?: { values: number[]; alarmFromIndex: number }
}

export type ReportTimelineColor = 'danger' | 'muted' | 'success'

export interface ReportTimelineEntry {
    label: string
    time: string
    /** Mono chip at the end of the row, e.g. a commit sha or a duration */
    chip: string
    color: ReportTimelineColor
}

export interface ReportImpactTile {
    value: string
    label: string
    note?: string
}

export interface ReportFixChange {
    file: string
    snippet: string
    note?: string
}

export interface ReportFixPlan {
    /** One paragraph describing the change */
    summary: string
    /** Where the lifecycle starts; 'launched' for fixes that already shipped */
    initialPhase?: ReportFixPhase
    flagKey: string
    /** Branch the fix PR ships on, e.g. "fix/rpt-1042-api-key-errors" */
    branch: string
    prTitle: string
    /** Checklist stepped through while the demo generates the code change */
    generationSteps: string[]
    /** Prompt copied for external coding agents */
    agentPrompt: string
    changes: ReportFixChange[]
    monitoringCriteria: string
}

/** Full report-page content. Rendered live by the report scene; charts tick in the background. */
export interface DemoReportContent {
    observation: {
        /** e.g. "People hitting the dead Create key click" */
        label: string
        /** Headline + tooltip unit, e.g. "users/hr" */
        unit: string
        chart: DemoChartData
        /** Bounds for new points the live ticker appends */
        liveRange: [number, number]
    }
    /** Occurrence bar strip under the observation chart */
    occurrences?: { label: string; values: number[]; alarmFromIndex: number }
    /** Mock screenshot of the error UI, shown at the top of the evidence rail */
    screenshot?: DemoScreenshot
    evidence: ReportEvidenceCard[]
    /** Pre-fix history; the fix lifecycle appends its own rows */
    timeline: ReportTimelineEntry[]
    /** Plain-language h1 for the report body */
    verdictHeadline: string
    problem: string[]
    /** Caption for the session replay figure, when replays are part of the evidence */
    replayCaption?: string
    impactTiles: ReportImpactTile[]
    howWeKnow: string[]
    /** The diff that introduced the problem, when the cause is a code change */
    causeDiff?: { title: string; snippet: string }
    /** Absent while the investigation is still running, or when the report was dismissed or disputed */
    fix?: ReportFixPlan
}

export interface DemoReport {
    id: string
    headline: string
    /** Mono area tag, e.g. "SETTINGS · AUTH" */
    area: string
    /** Headline impact figure, e.g. "1,410 users" or "p75 +1.2s" */
    impact: string
    trend: ReportTrend
    /** Sort weight, higher = more impact */
    impactWeight: number
    /** Age in hours */
    ageHours: number
    /** Shown under the "For you" scope: assigned to the viewer or in an area they work on */
    forYou?: boolean
    /** Display creation time, e.g. "Aug 17, 16:12" */
    created: string
    status: ReportStatus
    unread?: boolean
    /** True while the engine is still investigating (rotating activity phrase + shimmer) */
    live?: boolean
    /** One-paragraph verdict shown in the row preview and focus card */
    verdict: string
    /** Mono proof line, e.g. "214 session replays · 6 tickets" */
    proof: string
    /** Seven-point volume trend drawn as mini bars on the grouped inbox row */
    sparkline: number[]
    /** Signal sources the insight was built from, shown as chips on the row */
    sources: string[]
    focus?: ReportFocusContent
    /** Full report-page content. Required, so every row in the inbox opens a real report. */
    content: DemoReportContent
}

/** Fix lifecycle phases on the full report page. */
export type ReportFixPhase = 'reported' | 'generating' | 'proposed' | 'sent' | 'committed' | 'launched'

export type InboxDemoFilter = 'all' | 'open' | 'monitoring' | 'archived'
/** Which reports tab layout the inbox renders; switched from the internal section of Settings. */
export type InboxDemoLayout = 'list' | 'grouped'
export type InboxDemoSort = 'users' | 'recency'
/** Sections of the grouped inbox layout, in display order. */
export type InboxDemoGroup = 'decision' | 'monitoring' | 'resolved'
export type InboxDemoScope = 'for-you' | 'project'
export type InboxDemoTab = 'reports' | 'scouts' | 'settings'

/** One scout: a watcher that reads signal sources and opens reports. */
export interface DemoScout {
    id: string
    name: string
    /** What it watches, one sentence */
    watches: string
    /** e.g. "every 30m" */
    cadence: string
    lastRun: string
    openReports: number
    enabled: boolean
}

/** One demo settings toggle; `enabled` seeds the toggle map in the inbox logic. */
export interface DemoToggleRow {
    key: string
    label: string
    detail?: string
    enabled: boolean
}

/** Status a focus-mode action stamps on a report. */
export type FocusActedStatus = 'Archived' | 'Dismissed' | 'In progress'
