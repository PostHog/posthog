export interface RecordingView {
    sessionId: string
    personLabel: string
    startedAt: string | null
    endedAt: string | null
    durationSeconds: number
    clickCount: number
    consoleErrorCount: number
    startPath: string | null
    ongoing: boolean
    activityScore: number | null
}

export type TimelineKind = 'pageview' | 'click' | 'rageclick' | 'exception'

export interface TimelineEntry {
    key: string
    kind: TimelineKind
    /** Milliseconds from the recording start, never negative. */
    offsetMs: number
    /** `**bold**` marks the page, the element or the error. */
    text: string
    event: string
    issueId: string | null
}

export interface TimelineGroup {
    /** Start of the minute the group's entries fall in, in milliseconds from the recording start. */
    startMs: number
    entries: TimelineEntry[]
}

export interface SessionTimeline {
    groups: TimelineGroup[]
    eventCount: number
    truncated: boolean
    pageviewCount: number
    rageclickCount: number
    exceptionCount: number
    firstExceptionMs: number | null
    mainPath: string | null
    device: string | null
    city: string | null
}

export interface SummaryChapter {
    index: number
    startMs: number
    endMs: number | null
    frameMs: number | null
    title: string
    hasFrame: boolean
    isKeyMoment: boolean
}

export interface SessionSummary {
    observationId: string
    title: string
    text: string
    chapters: SummaryChapter[]
    keyMomentMs: number | null
    /** The scan's own 0 to 1 judgment of how worth watching the session is. */
    notability: number | null
    notabilityReason: string | null
    hasThumbnail: boolean
    scannedAt: string | null
}

export type SummaryState =
    | { kind: 'ready'; summary: SessionSummary }
    | { kind: 'running' }
    /** The newest summary scan ended without a summary. The server treats it as final, so Summarize would not retry. */
    | { kind: 'failed'; reason: string | null }
    | { kind: 'none' }

export interface SessionListRow {
    sessionId: string
    title: string | null
    personLabel: string
    startedAt: string | null
    durationSeconds: number | null
    keyMomentMs: number | null
    notability: number | null
    clickCount: number | null
    consoleErrorCount: number | null
    startPath: string | null
    thumbnailObservationId: string | null
}
