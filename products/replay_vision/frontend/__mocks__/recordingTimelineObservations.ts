import type { ReplayObservationApi } from '../generated/api.schemas'

// Fixtures for the recording timeline's stories: a summary with chapters and idle, and scans with key moments.
export const MIN = 60_000
let nextId = 1
const id = (): string => `0198f2a1-0000-7000-8000-${String(nextId++).padStart(12, '0')}`

export interface ChapterSpec {
    start: number
    end: number
    title: string
    frame?: boolean
}

export function summary({
    chapters = [],
    inactive = [],
    status = 'succeeded',
    legacyIdle = false,
}: {
    chapters?: ChapterSpec[]
    inactive?: [number, number][]
    status?: ReplayObservationApi['status']
    legacyIdle?: boolean
}): ReplayObservationApi {
    const output: Record<string, unknown> = {
        scanner_type: 'summarizer',
        title: 'Session summary',
        summary: '',
        confidence: 0.8,
        chapters: chapters.map((c) => ({
            kind: 'activity',
            start_ms: c.start,
            end_ms: c.end,
            title: c.title,
            thumbnail_ms: Math.round((c.start + c.end) / 2),
        })),
    }
    if (legacyIdle) {
        output.chapters = (output.chapters as Record<string, unknown>[]).flatMap((c, i) =>
            i === 0 ? [c] : [{ kind: 'idle', start_ms: c.start_ms, end_ms: c.start_ms, title: 'Idle' }, c]
        )
    } else {
        output.inactive_periods = inactive.map(([start, end]) => ({ start_ms: start, end_ms: end }))
    }
    return {
        id: id(),
        session_id: 'session-1',
        status,
        created_at: '2026-10-02T09:00:00Z',
        scanner_origin: 'inline',
        scanner_snapshot: { name: 'Quick summary', scanner_type: 'summarizer', scanner_config: {} },
        scanner_result: status === 'succeeded' ? { model_output: output } : null,
        media: chapters.flatMap((c, position) =>
            c.frame === false ? [] : [{ id: id(), kind: 'chapter', position, asset_id: 1 }]
        ),
    } as unknown as ReplayObservationApi
}

function scan(
    scannerType: 'monitor' | 'scorer' | 'classifier',
    name: string,
    keyMomentMs: number | null,
    answer: Record<string, unknown>
): ReplayObservationApi {
    return {
        id: id(),
        session_id: 'session-1',
        status: 'succeeded',
        created_at: '2026-10-02T09:05:00Z',
        scanner_origin: 'configured',
        scanner_snapshot: { name, scanner_type: scannerType, scanner_config: {} },
        scanner_result: {
            model_output: { scanner_type: scannerType, confidence: 0.8, key_moment_ms: keyMomentMs, ...answer },
        },
        media: [],
    } as unknown as ReplayObservationApi
}

export const checkoutMonitor = (at: number | null): ReplayObservationApi =>
    scan('monitor', 'Struggled at checkout', at, { verdict: 'yes', reasoning: '' })
export const frustrationScorer = (at: number | null): ReplayObservationApi =>
    scan('scorer', 'Frustration', at, { score: 4, reasoning: '' })
export const intentClassifier = (at: number | null): ReplayObservationApi =>
    scan('classifier', 'Visit intent', at, { tags: ['Pricing research'], reasoning: '' })

export const SHORT = [
    { start: 0, end: 18_000, title: 'Browses surveys product page' },
    { start: 18_000, end: 39_000, title: 'Reviews survey use cases table' },
    { start: 39_000, end: 61_000, title: 'Opens install with AI prompt' },
]

export const MEDIUM = [
    { start: 0, end: 52_000, title: 'Searches for winter jackets' },
    { start: 52_000, end: 118_000, title: 'Compares three parka product pages' },
    { start: 131_000, end: 176_000, title: 'Adds insulated parka to cart' },
    { start: 176_000, end: 214_000, title: 'Applies discount code at checkout' },
    { start: 214_000, end: 236_000, title: 'Payment form rejects card' },
    { start: 236_000, end: 291_000, title: 'Retries payment with a second card' },
]
export const MEDIUM_INACTIVE: [number, number][] = [
    [118_000, 131_000],
    [140_000, 146_000],
]

export const LONG: ChapterSpec[] = [
    { start: 0, end: 3 * MIN, title: 'Signs in and opens the dashboard' },
    { start: 3 * MIN, end: 7 * MIN, title: 'Filters revenue report by region' },
    { start: 17 * MIN, end: 21 * MIN, title: 'Exports quarterly revenue to CSV' },
    { start: 21 * MIN, end: 34 * MIN, title: 'Edits invoice line items' },
    { start: 44 * MIN, end: 47 * MIN, title: 'Opens billing settings' },
    { start: 47 * MIN, end: 52 * MIN, title: 'Updates payment method details' },
    { start: 52 * MIN, end: 58 * MIN, title: 'Invites a teammate to the workspace' },
]
export const LONG_INACTIVE: [number, number][] = [
    [7 * MIN, 17 * MIN],
    [25 * MIN, 31 * MIN],
    [34 * MIN, 44 * MIN],
    [58 * MIN, 61 * MIN],
]

export const VERY_LONG: ChapterSpec[] = Array.from({ length: 20 }, (_, i) => ({
    start: i * 9 * MIN,
    end: i * 9 * MIN + 6 * MIN,
    title: [
        'Triages alerts on the sensor dashboard',
        'Acknowledges the cooling unit alert',
        'Reviews sensor history for unit 4',
        'Opens the maintenance ticket form',
        'Assigns the ticket to the on-call engineer',
    ][i % 5],
}))
export const VERY_LONG_INACTIVE: [number, number][] = VERY_LONG.map((c) => [c.end, c.end + 3 * MIN])
