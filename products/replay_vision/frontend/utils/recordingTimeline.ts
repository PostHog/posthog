import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    VERDICT_LABEL,
    isFlaggedObservation,
    isSummaryObservation,
    readModelOutput,
    readScore,
    readTags,
    readVerdict,
    scannerLabel,
} from './observation'

/** Shorter idle is a pause in the flow of a chapter, not something worth a row of its own. */
export const MIN_INACTIVE_ROW_MS = 30_000

export interface TimelineChapter {
    /** Index into the summary's `model_output.chapters`, which is how the chapter's frame is fetched. */
    position: number
    startMs: number
    endMs: number
    title: string
    hasFrame: boolean
    /** Inactive time inside the chapter, from pauses the chapter spans. */
    inactiveMs: number
}

export interface TimelineInactive {
    startMs: number
    endMs: number
}

export interface TimelineMarker {
    observationId: string
    timestampMs: number
    scannerName: string
    scannerType: string | null
    /** The answer the run gave, for example "Yes", "Score 4" or a tag; null when it has none to show. */
    result: string | null
    flagged: boolean
}

/**
 * What the timeline can show for this recording:
 * `ready` has chapters, `pending` has a summary still running, `outdated` has a summary that predates chapters,
 * and `none` has no summary at all.
 */
export type SummaryState = 'ready' | 'pending' | 'outdated' | 'none'

export interface RecordingTimeline {
    summary: ReplayObservationApi | null
    summaryState: SummaryState
    chapters: TimelineChapter[]
    inactive: TimelineInactive[]
    markers: TimelineMarker[]
}

/** One row on the rail. */
export type TimelineRow =
    | { kind: 'chapter'; chapter: TimelineChapter }
    | { kind: 'inactive'; startMs: number; endMs: number }
    | { kind: 'boundary'; edge: 'start' | 'end'; atMs: number }

// Rows are spaced by elapsed time, capped so one quiet stretch can't push the rest off screen.
const TIMELINE_GAP_PX_PER_SECOND = 0.3
export const TIMELINE_GAP_MAX_PX = 20

export function timelineGapPx(deltaMs: number): number {
    return Math.min(TIMELINE_GAP_MAX_PX, Math.max(0, (deltaMs / 1000) * TIMELINE_GAP_PX_PER_SECOND))
}

function readNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function readChapters(summary: ReplayObservationApi): TimelineChapter[] {
    const raw = readModelOutput(summary)?.chapters
    if (!Array.isArray(raw)) {
        return []
    }
    const framePositions = new Set(
        (summary.media ?? []).filter((entry) => entry.kind === 'chapter').map((entry) => entry.position)
    )
    const chapters: TimelineChapter[] = []
    raw.forEach((entry: unknown, position) => {
        if (!entry || typeof entry !== 'object') {
            return
        }
        const chapter = entry as Record<string, unknown>
        const startMs = readNumber(chapter.start_ms)
        const endMs = readNumber(chapter.end_ms)
        // Summaries written before inactive periods existed list idle as chapters; the gaps carry it now.
        if (chapter.kind === 'idle' || startMs === null || endMs === null || endMs <= startMs) {
            return
        }
        chapters.push({
            position,
            startMs,
            endMs,
            title: typeof chapter.title === 'string' ? chapter.title : '',
            hasFrame: framePositions.has(position),
            inactiveMs: 0,
        })
    })
    return chapters.sort((a, b) => a.startMs - b.startMs)
}

function readInactive(summary: ReplayObservationApi): TimelineInactive[] {
    const output = readModelOutput(summary)
    const periods = output?.inactive_periods
    const chapters = output?.chapters
    // Summaries written before inactive periods existed list idle as chapters instead.
    const raw: unknown[] = Array.isArray(periods)
        ? periods
        : Array.isArray(chapters)
          ? chapters.filter((c: unknown) => (c as Record<string, unknown> | null)?.kind === 'idle')
          : []
    return raw
        .map((entry: unknown) => {
            const period = (entry ?? {}) as Record<string, unknown>
            return { startMs: readNumber(period.start_ms), endMs: readNumber(period.end_ms) }
        })
        .filter((p): p is TimelineInactive => p.startMs !== null && p.endMs !== null && p.endMs > p.startMs)
        .sort((a, b) => a.startMs - b.startMs)
}

function markerResult(observation: ReplayObservationApi): string | null {
    const verdict = readVerdict(observation)
    if (verdict) {
        return VERDICT_LABEL[verdict]
    }
    const score = readScore(observation)
    if (score !== null) {
        return `Score ${score}`
    }
    const tags = readTags(observation)
    return tags.length > 0 ? tags.join(', ') : null
}

function readMarker(observation: ReplayObservationApi): TimelineMarker | null {
    const timestampMs = readNumber(readModelOutput(observation)?.key_moment_ms)
    if (observation.status !== 'succeeded' || timestampMs === null) {
        return null
    }
    return {
        observationId: observation.id,
        timestampMs,
        scannerName: scannerLabel(observation),
        scannerType: observation.scanner_snapshot?.scanner_type ?? null,
        result: markerResult(observation),
        flagged: isFlaggedObservation(observation),
    }
}

function overlapMs(a: TimelineInactive, startMs: number, endMs: number): number {
    return Math.max(0, Math.min(a.endMs, endMs) - Math.max(a.startMs, startMs))
}

function uncoveredParts(period: TimelineInactive, chapters: TimelineChapter[]): TimelineInactive[] {
    let parts = [period]
    for (const c of chapters) {
        parts = parts.flatMap((p) =>
            [
                { startMs: p.startMs, endMs: Math.min(p.endMs, c.startMs) },
                { startMs: Math.max(p.startMs, c.endMs), endMs: p.endMs },
            ].filter((part) => part.endMs > part.startMs)
        )
    }
    return parts
}

/** The recording's timeline: the newest summary's chapters, with every other run's key moment as a marker. */
export function recordingTimeline(observations: ReplayObservationApi[]): RecordingTimeline {
    const summaries = observations
        .filter(isSummaryObservation)
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    const summary = summaries.find((o) => o.status === 'succeeded') ?? null
    const pending = summaries.some((o) => o.status === 'pending' || o.status === 'running')
    const markers = observations
        .filter((o) => !isSummaryObservation(o))
        .map(readMarker)
        .filter((m): m is TimelineMarker => m !== null)
        .sort((a, b) => a.timestampMs - b.timestampMs)

    const chapters = summary ? readChapters(summary) : []
    const allInactive = summary ? readInactive(summary) : []
    for (const chapter of chapters) {
        chapter.inactiveMs = allInactive.reduce((sum, p) => sum + overlapMs(p, chapter.startMs, chapter.endMs), 0)
    }
    // A gap row is the inactive time no chapter covers, so a pause a chapter spans never shows twice.
    const inactive = allInactive
        .flatMap((p) => uncoveredParts(p, chapters))
        .filter((p) => p.endMs - p.startMs >= MIN_INACTIVE_ROW_MS)

    const summaryState: SummaryState =
        chapters.length > 0 ? 'ready' : pending ? 'pending' : summary ? 'outdated' : 'none'
    return { summary, summaryState, chapters, inactive, markers }
}

/** The rows the sidebar lists, in time order: the session's ends, chapters and idle gaps. Empty without chapters. */
export function timelineRows(timeline: RecordingTimeline, durationMs: number | null = null): TimelineRow[] {
    if (timeline.chapters.length === 0) {
        return []
    }
    const rows: { atMs: number; order: number; row: TimelineRow }[] = []
    rows.push({ atMs: 0, order: -1, row: { kind: 'boundary', edge: 'start', atMs: 0 } })
    for (const chapter of timeline.chapters) {
        rows.push({ atMs: chapter.startMs, order: 0, row: { kind: 'chapter', chapter } })
    }
    for (const gap of timeline.inactive) {
        rows.push({ atMs: gap.startMs, order: 1, row: { kind: 'inactive', startMs: gap.startMs, endMs: gap.endMs } })
    }
    if (durationMs !== null && durationMs > 0) {
        // The player's length can come up short of what the scan saw, and the end must still close the rail.
        const endMs = Math.max(durationMs, ...timeline.chapters.map((c) => c.endMs))
        rows.push({ atMs: endMs, order: 3, row: { kind: 'boundary', edge: 'end', atMs: endMs } })
    }
    return rows.sort((a, b) => a.atMs - b.atMs || a.order - b.order).map(({ row }) => row)
}

/** Where a row sits on the recording's clock, which the rail spaces and the player highlights by. */
export function rowStartMs(row: TimelineRow): number {
    switch (row.kind) {
        case 'chapter':
            return row.chapter.startMs
        case 'inactive':
            return row.startMs
        case 'boundary':
            return row.atMs
    }
}

/** The row the player is in: the last one that started at or before the player's position, or -1 before the first. */
export function currentRowIndex(rows: TimelineRow[], playerTimeMs: number): number {
    let current = -1
    rows.forEach((row, index) => {
        if (rowStartMs(row) <= playerTimeMs) {
            current = index
        }
    })
    return current
}

/** The next chapter start after the player's position. */
export function nextTimelineStopMs(timeline: RecordingTimeline, playerTimeMs: number): number | null {
    const later = timeline.chapters.map((c) => c.startMs).filter((ms) => ms > playerTimeMs)
    return later.length > 0 ? Math.min(...later) : null
}
