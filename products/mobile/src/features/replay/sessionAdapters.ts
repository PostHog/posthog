import {
    type RecordingApi,
    type RecordingPersonApi,
    SESSION_ACTIVITY_LIMIT,
    type SessionEventsApi,
} from '@/api/recordings'
import type { ObservationApi, SummaryChapterApi, WatchFeedItemApi } from '@/api/replayVision'
import { formatRelativeAgo } from '@/lib/dates'
import { asRecord } from '@/lib/records'
import { plural, truncate } from '@/model/adapters/text'

import type {
    RecordingView,
    SessionListRow,
    SessionSummary,
    SessionTimeline,
    SummaryChapter,
    SummaryState,
    TimelineEntry,
    TimelineGroup,
    TimelineKind,
} from './replayModel'

const ANONYMOUS = 'Anonymous person'
/** A distinct id this long with no spaces is a generated id, not something a person would read. */
const GENERATED_ID_LENGTH = 20

function text(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function count(value: unknown): number {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function personLabel(
    person: RecordingPersonApi | null | undefined,
    distinctId?: string | null,
    email?: string | null
): string {
    const properties = asRecord(person?.properties)
    const label =
        text(properties?.email) ??
        text(properties?.name) ??
        text(properties?.$name) ??
        text(email) ??
        text(person?.name) ??
        text(person?.distinct_ids?.[0]) ??
        text(distinctId)
    if (!label) {
        return ANONYMOUS
    }
    if (label.length >= GENERATED_ID_LENGTH && !/[\s@]/.test(label)) {
        // A UUIDv7 starts with the time, so its start is the same for everyone that day; the end tells people apart.
        return `Person ${label
            .replace(/[^a-z0-9]/gi, '')
            .slice(-4)
            .toLowerCase()}`
    }
    return label
}

export function urlPath(url: string | null | undefined): string | null {
    const value = text(url)
    if (!value) {
        return null
    }
    const match = /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*(.*)$/i.exec(value)
    if (!match) {
        return value
    }
    return match[1] || '/'
}

export function recordingView(api: RecordingApi): RecordingView {
    return {
        sessionId: api.id,
        personLabel: personLabel(api.person, api.distinct_id),
        startedAt: text(api.start_time),
        endedAt: text(api.end_time),
        durationSeconds: Math.max(0, Math.round(count(api.recording_duration))),
        clickCount: count(api.click_count),
        consoleErrorCount: count(api.console_error_count),
        startPath: urlPath(api.start_url),
        ongoing: api.ongoing === true,
        activityScore: typeof api.activity_score === 'number' ? api.activity_score : null,
    }
}

export function formatOffset(ms: number): string {
    const total = Math.max(0, Math.floor(ms / 1000))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = String(total % 60).padStart(2, '0')
    return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

export function formatDuration(seconds: number): string {
    const total = Math.max(0, Math.round(seconds))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const rest = total % 60
    if (hours > 0) {
        return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`
    }
    if (minutes > 0) {
        return rest > 0 ? `${minutes} min ${rest} s` : `${minutes} min`
    }
    return `${rest} s`
}

export function formatShortDuration(seconds: number): string {
    if (seconds < 60) {
        return formatDuration(seconds)
    }
    const minutes = Math.round(seconds / 60)
    return minutes >= 60 ? formatDuration(minutes * 60) : `${minutes} min`
}

// Bold markers in the timeline come from the app; the page, element and error text come from the customer's site.
function plain(value: string): string {
    return value.replace(/\*/g, '')
}

function stringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.filter((item): item is string => typeof item === 'string')
    }
    if (typeof value === 'string' && value.startsWith('[')) {
        try {
            return stringArray(JSON.parse(value) as unknown)
        } catch {
            return []
        }
    }
    const single = text(value)
    return single ? [single] : []
}

interface EventRow {
    timestamp: string
    event: string
    path: string | null
    elementText: string | null
    issueId: string | null
    exceptionType: string | null
    exceptionMessage: string | null
    browser: string | null
    os: string | null
    city: string | null
}

function eventRow(row: unknown[]): EventRow | null {
    const [
        timestamp,
        event,
        currentUrl,
        pathname,
        screenName,
        elementTexts,
        ,
        issueId,
        types,
        values,
        browser,
        os,
        city,
    ] = row
    const at = text(timestamp)
    const name = text(event)
    if (!at || !name) {
        return null
    }
    return {
        timestamp: at,
        event: name,
        path: text(screenName) ?? text(pathname) ?? urlPath(text(currentUrl)),
        elementText:
            stringArray(elementTexts)
                .map((item) => item.trim())
                .find(Boolean) ?? null,
        issueId: text(issueId),
        exceptionType: stringArray(types)[0] ?? null,
        exceptionMessage: stringArray(values)[0] ?? null,
        browser: text(browser),
        os: text(os),
        city: text(city),
    }
}

function kindOf(event: string): TimelineKind | null {
    switch (event) {
        case '$pageview':
        case '$screen':
            return 'pageview'
        case '$autocapture':
            return 'click'
        case '$rageclick':
            return 'rageclick'
        case '$exception':
            return 'exception'
        default:
            return null
    }
}

function entryText(kind: TimelineKind, row: EventRow): string {
    const element = row.elementText ? `**${plain(truncate(row.elementText, 60))}**` : null
    const path = row.path ? `**${plain(truncate(row.path, 80))}**` : null
    switch (kind) {
        case 'pageview':
            return path ? `Viewed ${path}` : 'Viewed a page'
        case 'click':
            return element ? `Clicked ${element}` : path ? `Clicked on ${path}` : 'Clicked'
        case 'rageclick':
            return element ? `Rage clicked ${element}` : path ? `Rage clicked on ${path}` : 'Rage clicked'
        case 'exception': {
            const type = row.exceptionType ? `**${plain(truncate(row.exceptionType, 60))}**` : '**Error**'
            const message = row.exceptionMessage ? ` ${plain(truncate(row.exceptionMessage, 120))}` : ''
            return `${type}${message}`
        }
    }
}

export const TIMELINE_MAX_ENTRIES = 60
const TIMELINE_MAX_CLICKS = 20

function sampleClicks(clicks: TimelineEntry[], max: number): TimelineEntry[] {
    if (clicks.length <= max) {
        return clicks
    }
    const step = clicks.length / max
    return Array.from({ length: max }, (_, index) => clicks[Math.floor(index * step)]).filter(
        (entry): entry is TimelineEntry => entry !== undefined
    )
}

function mostCommon(values: readonly string[]): string | null {
    const counts = new Map<string, number>()
    let best: string | null = null
    let bestCount = 0
    for (const value of values) {
        const next = (counts.get(value) ?? 0) + 1
        counts.set(value, next)
        if (next > bestCount) {
            best = value
            bestCount = next
        }
    }
    return best
}

function eventRows(results: unknown[][] | undefined): EventRow[] {
    return (results ?? []).map(eventRow).filter((row): row is EventRow => row !== null)
}

export function sessionTimeline(events: SessionEventsApi, startTime: string): SessionTimeline {
    const start = new Date(startTime).getTime()
    const activity = eventRows(events.activity.results)
    const rows = [...activity, ...eventRows(events.problems.results)].sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )
    const entries: TimelineEntry[] = []
    let lastPath: string | null = null
    rows.forEach((row, index) => {
        const kind = kindOf(row.event)
        if (!kind) {
            return
        }
        if (kind === 'pageview') {
            // A single-page app can send the same page view twice in a row.
            if (row.path !== null && row.path === lastPath) {
                return
            }
            lastPath = row.path
        }
        entries.push({
            key: `${index}:${row.timestamp}`,
            kind,
            offsetMs: Math.max(0, new Date(row.timestamp).getTime() - start),
            text: entryText(kind, row),
            event: row.event,
            issueId: kind === 'exception' ? row.issueId : null,
        })
    })
    const of = (kind: TimelineKind): TimelineEntry[] => entries.filter((entry) => entry.kind === kind)
    const problems = [...of('exception'), ...of('rageclick')].slice(0, TIMELINE_MAX_ENTRIES)
    const pages = of('pageview').slice(0, TIMELINE_MAX_ENTRIES - problems.length)
    const clicks = sampleClicks(
        of('click'),
        Math.min(TIMELINE_MAX_CLICKS, TIMELINE_MAX_ENTRIES - problems.length - pages.length)
    )
    const kept = [...problems, ...pages, ...clicks].sort((a, b) => a.offsetMs - b.offsetMs)

    const groups: TimelineGroup[] = []
    for (const entry of kept) {
        const minute = Math.floor(entry.offsetMs / 60_000) * 60_000
        const last = groups[groups.length - 1]
        if (last && last.startMs === minute) {
            last.entries.push(entry)
        } else {
            groups.push({ startMs: minute, entries: [entry] })
        }
    }

    const exceptions = of('exception')
    const firstNamed = rows.find((row) => row.browser || row.os)
    const device = firstNamed
        ? [firstNamed.browser, firstNamed.os].filter(Boolean).join(firstNamed.browser && firstNamed.os ? ' on ' : '')
        : null
    return {
        groups,
        eventCount: rows.length,
        truncated: activity.length >= SESSION_ACTIVITY_LIMIT,
        pageviewCount: of('pageview').length,
        rageclickCount: of('rageclick').length,
        exceptionCount: exceptions.length,
        firstExceptionMs: exceptions[0]?.offsetMs ?? null,
        mainPath: mostCommon(
            rows.filter((row) => kindOf(row.event) === 'pageview' && row.path).map((row) => row.path as string)
        ),
        device: device || null,
        city: rows.find((row) => row.city)?.city ?? null,
    }
}

export function nearestEntryKey(timeline: SessionTimeline, ms: number): string | null {
    let best: { key: string; distance: number } | null = null
    for (const entry of timeline.groups.flatMap((group) => group.entries)) {
        const distance = Math.abs(entry.offsetMs - ms)
        if (!best || distance < best.distance) {
            best = { key: entry.key, distance }
        }
    }
    return best?.key ?? null
}

export function fallbackTitle(recording: RecordingView, timeline: SessionTimeline | null): string {
    const length = formatShortDuration(recording.durationSeconds)
    const path = timeline?.mainPath ?? recording.startPath
    const problems = [
        timeline && timeline.exceptionCount > 0 ? plural(timeline.exceptionCount, 'error') : null,
        timeline && timeline.rageclickCount > 0 ? plural(timeline.rageclickCount, 'rage click') : null,
    ].filter((part): part is string => part !== null)
    return [length, path ? `on ${path}` : null, problems.length > 0 ? `with ${problems.join(' and ')}` : null]
        .filter(Boolean)
        .join(' ')
}

function isSummarizer(observation: ObservationApi): boolean {
    return (
        observation.scanner_result?.model_output?.scanner_type === 'summarizer' ||
        observation.scanner_snapshot?.scanner_type === 'summarizer'
    )
}

function chapterEnd(chapters: readonly SummaryChapterApi[], index: number): number | null {
    const own = chapters[index]?.end_ms
    if (typeof own === 'number') {
        return own
    }
    const next = chapters[index + 1]?.start_ms
    return typeof next === 'number' ? next : null
}

export function sessionSummary(observation: ObservationApi): SessionSummary {
    const output = observation.scanner_result?.model_output ?? {}
    const keyMomentMs = typeof output.key_moment_ms === 'number' ? output.key_moment_ms : null
    const media = observation.media ?? []
    const rawChapters = output.chapters ?? []
    const chapters: SummaryChapter[] = rawChapters.flatMap((chapter, index): SummaryChapter[] => {
        if (chapter.kind === 'idle' || typeof chapter.start_ms !== 'number' || !chapter.title) {
            return []
        }
        const endMs = chapterEnd(rawChapters, index)
        return [
            {
                index,
                startMs: chapter.start_ms,
                endMs,
                frameMs: typeof chapter.thumbnail_ms === 'number' ? chapter.thumbnail_ms : null,
                title: chapter.title,
                hasFrame: media.some((item) => item.kind === 'chapter' && item.position === index),
                isKeyMoment:
                    keyMomentMs !== null && keyMomentMs >= chapter.start_ms && (endMs === null || keyMomentMs < endMs),
            },
        ]
    })
    return {
        observationId: observation.id,
        title: text(output.title) ?? text(observation.summary_line) ?? 'Session summary',
        text: text(output.summary) ?? '',
        chapters,
        keyMomentMs,
        notability: typeof output.notability === 'number' ? output.notability : null,
        notabilityReason: text(output.notability_reason),
        hasThumbnail: media.some((item) => item.kind === 'thumbnail'),
        scannedAt: text(observation.completed_at) ?? text(observation.created_at),
    }
}

function ineligibleReason(errorReason: string | undefined): string | null {
    const message = text(errorReason?.slice(errorReason.indexOf(':') + 1))
    if (!message) {
        return null
    }
    const sentence = message.charAt(0).toUpperCase() + message.slice(1)
    return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`
}

/**
 * The newest succeeded summary wins over a scan still running, so a re-scan never hides a summary already there.
 * Only summarizer scans count: a monitor's one-line answer is not a summary of the session.
 */
export function summaryState(observations: readonly ObservationApi[]): SummaryState {
    const summaries = observations.filter(isSummarizer)
    const ready = summaries.find((observation) => observation.status === 'succeeded')
    if (ready) {
        return { kind: 'ready', summary: sessionSummary(ready) }
    }
    if (summaries.some((observation) => observation.status === 'pending' || observation.status === 'running')) {
        return { kind: 'running' }
    }
    const ended = summaries.find(
        (observation) => observation.status === 'failed' || observation.status === 'ineligible'
    )
    if (ended) {
        return { kind: 'failed', reason: ended.status === 'ineligible' ? ineligibleReason(ended.error_reason) : null }
    }
    return { kind: 'none' }
}

export function sessionListRows(
    feed: readonly WatchFeedItemApi[],
    recordings: readonly RecordingApi[]
): SessionListRow[] {
    const recordingsById = new Map(recordings.map((recording) => [recording.id, recording]))
    const seen = new Set<string>()
    const rows: SessionListRow[] = []
    for (const { observation, reason } of feed) {
        if (seen.has(observation.session_id)) {
            continue
        }
        seen.add(observation.session_id)
        const output = observation.scanner_result?.model_output ?? {}
        const recording = recordingsById.get(observation.session_id)
        const view = recording ? recordingView(recording) : null
        rows.push({
            sessionId: observation.session_id,
            title:
                text(output.title) ??
                (text(observation.summary_line) ? truncate(observation.summary_line ?? '', 100) : null),
            personLabel:
                view?.personLabel ?? personLabel(null, observation.distinct_id, observation.recording_subject_email),
            startedAt: view?.startedAt ?? null,
            durationSeconds: view?.durationSeconds ?? null,
            keyMomentMs: typeof output.key_moment_ms === 'number' ? output.key_moment_ms : null,
            notability:
                typeof output.notability === 'number'
                    ? output.notability
                    : typeof reason.notability === 'number'
                      ? reason.notability
                      : null,
            clickCount: view?.clickCount ?? null,
            consoleErrorCount: view?.consoleErrorCount ?? null,
            startPath: view?.startPath ?? null,
            thumbnailObservationId: (observation.media ?? []).some((item) => item.kind === 'thumbnail')
                ? observation.id
                : null,
        })
    }
    for (const recording of recordings) {
        if (seen.has(recording.id)) {
            continue
        }
        seen.add(recording.id)
        const view = recordingView(recording)
        rows.push({
            sessionId: view.sessionId,
            title: null,
            personLabel: view.personLabel,
            startedAt: view.startedAt,
            durationSeconds: view.durationSeconds,
            keyMomentMs: null,
            notability: null,
            clickCount: view.clickCount,
            consoleErrorCount: view.consoleErrorCount,
            startPath: view.startPath,
            thumbnailObservationId: null,
        })
    }
    return rows
}

export function sessionRowMeta(row: SessionListRow, now: Date): string[] {
    return [
        row.personLabel,
        row.durationSeconds !== null ? formatShortDuration(row.durationSeconds) : null,
        row.keyMomentMs !== null ? `key moment ${formatOffset(row.keyMomentMs)}` : null,
        row.title === null && row.startPath ? row.startPath : null,
        row.startedAt ? formatRelativeAgo(row.startedAt, now) : null,
    ].filter((part): part is string => Boolean(part))
}

export function sessionRowTitle(row: SessionListRow): string {
    if (row.title) {
        return row.title
    }
    return [
        'Session',
        row.clickCount !== null ? plural(row.clickCount, 'click') : null,
        row.consoleErrorCount ? plural(row.consoleErrorCount, 'error') : null,
    ]
        .filter(Boolean)
        .join(' · ')
}
