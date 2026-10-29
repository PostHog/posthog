import { type RecordingApi, SESSION_ACTIVITY_LIMIT, type SessionEventsApi } from '@/api/recordings'
import type { ObservationApi, WatchFeedItemApi } from '@/api/replayVision'

import { parseSeekSeconds, shareSeconds } from './replayLinks'
import {
    fallbackTitle,
    formatDuration,
    formatOffset,
    nearestEntryKey,
    personLabel,
    recordingView,
    sessionListRows,
    sessionTimeline,
    summaryState,
} from './sessionAdapters'

const START = '2026-10-21T20:14:00.000Z'

function at(seconds: number): string {
    return new Date(new Date(START).getTime() + seconds * 1000).toISOString()
}

/** One events row in `SESSION_EVENT_COLUMNS` order. */
function row(
    seconds: number,
    event: string,
    fields: { path?: string; text?: string; issueId?: string; type?: string; message?: string } = {}
): unknown[] {
    return [
        at(seconds),
        event,
        fields.path ? `https://app.example.com${fields.path}` : null,
        fields.path ?? null,
        null,
        fields.text ? [fields.text] : [],
        event === '$autocapture' ? 'click' : null,
        fields.issueId ?? null,
        fields.type ? JSON.stringify([fields.type]) : null,
        fields.message ? JSON.stringify([fields.message]) : null,
        'Chrome',
        'Mac OS X',
        'Lisbon',
    ]
}

/** Splits rows the way the two queries return them: page views and clicks, then errors and rage clicks. */
function events(rows: unknown[][]): SessionEventsApi {
    const problem = (item: unknown[]): boolean => item[1] === '$exception' || item[1] === '$rageclick'
    return {
        activity: { results: rows.filter((item) => !problem(item)) },
        problems: { results: rows.filter(problem) },
    }
}

function observation(overrides: Partial<ObservationApi> & { output?: Record<string, unknown> }): ObservationApi {
    const { output, ...rest } = overrides
    return {
        id: 'obs-1',
        scanner_id: 'scanner-1',
        session_id: 's-1',
        status: 'succeeded',
        scanner_snapshot: { scanner_type: 'summarizer' },
        scanner_result: { model_output: { scanner_type: 'summarizer', ...output } },
        media: [],
        created_at: START,
        ...rest,
    }
}

describe('session adapters', () => {
    test.each([
        [{ properties: { email: 'robin@example.com' } }, null, 'robin@example.com'],
        [{ name: '0192f3a8-6c1e-7d42-9b8e-3c5a8f3a1e07' }, null, 'Person 1e07'],
        [null, 'robin-calloway', 'robin-calloway'],
        [null, null, 'Anonymous person'],
    ])('labels a person %#', (person, distinctId, expected) => {
        expect(personLabel(person, distinctId)).toBe(expected)
    })

    test('formats offsets and durations', () => {
        expect(formatOffset(134_000)).toBe('2:14')
        expect(formatOffset(3_734_000)).toBe('1:02:14')
        expect(formatDuration(252)).toBe('4 min 12 s')
        expect(formatDuration(45)).toBe('45 s')
    })

    test('builds the timeline from the recording start, grouped by minute, errors linked to their issue', () => {
        const timeline = sessionTimeline(
            events([
                row(-2, '$pageview', { path: '/files' }),
                row(1, '$pageview', { path: '/files' }),
                row(48, '$autocapture', { text: 'Q3 plan.pdf' }),
                row(134, '$exception', { issueId: 'issue-9', type: 'TypeError', message: 'x is undefined' }),
                row(136, '$rageclick', { text: 'Create link' }),
            ]),
            START
        )
        expect(timeline.groups.map((group) => group.startMs)).toEqual([0, 120_000])
        const entries = timeline.groups.flatMap((group) => group.entries)
        // The repeated page view is dropped, and the one sent before the first snapshot sits at 0:00.
        expect(entries.map((entry) => [entry.kind, entry.offsetMs, entry.text])).toEqual([
            ['pageview', 0, 'Viewed **/files**'],
            ['click', 48_000, 'Clicked **Q3 plan.pdf**'],
            ['exception', 134_000, '**TypeError** x is undefined'],
            ['rageclick', 136_000, 'Rage clicked **Create link**'],
        ])
        expect(entries.find((entry) => entry.kind === 'exception')?.issueId).toBe('issue-9')
        expect(timeline).toMatchObject({
            firstExceptionMs: 134_000,
            device: 'Chrome on Mac OS X',
            city: 'Lisbon',
            mainPath: '/files',
        })
    })

    test('keeps an error that comes after the click query hit its cap', () => {
        const clicks = Array.from({ length: SESSION_ACTIVITY_LIMIT }, (_, index) =>
            row(index, '$autocapture', { text: `Item ${index}` })
        )
        const timeline = sessionTimeline(
            { activity: { results: clicks }, problems: { results: [row(400, '$exception', { type: 'TypeError' })] } },
            START
        )
        const entries = timeline.groups.flatMap((group) => group.entries)
        expect(entries.filter((entry) => entry.kind === 'click')).toHaveLength(20)
        expect(entries[entries.length - 1]).toMatchObject({ kind: 'exception', offsetMs: 400_000 })
        expect(timeline).toMatchObject({ eventCount: SESSION_ACTIVITY_LIMIT + 1, truncated: true })
        expect(nearestEntryKey(timeline, 390_000)).toBe(entries[entries.length - 1]?.key)
    })

    test('titles a session without a summary from its events', () => {
        const recording = recordingView({
            id: 's-1',
            recording_duration: 252,
            start_url: 'https://app.example.com/home',
        })
        const timeline = sessionTimeline(
            events([
                row(0, '$pageview', { path: '/files' }),
                row(10, '$exception', { type: 'TypeError' }),
                row(11, '$rageclick'),
                row(12, '$rageclick'),
                row(13, '$rageclick'),
            ]),
            START
        )
        expect(fallbackTitle(recording, timeline)).toBe('4 min on /files with 1 error and 3 rage clicks')
        expect(fallbackTitle({ ...recording, durationSeconds: 20 }, null)).toBe('20 s on /home')
    })

    test('a finished summary wins over a re-scan in flight, and other scanner types never count', () => {
        const running = observation({ id: 'obs-2', status: 'running', scanner_result: null })
        const done = observation({ output: { title: 'User gives up on sharing', summary: 'Text' } })
        const monitor = observation({
            id: 'obs-3',
            scanner_snapshot: { scanner_type: 'monitor' },
            scanner_result: { model_output: { scanner_type: 'monitor' } },
        })
        expect(summaryState([running, done])).toMatchObject({
            kind: 'ready',
            summary: { title: 'User gives up on sharing' },
        })
        expect(summaryState([running])).toEqual({ kind: 'running' })
        expect(summaryState([monitor])).toEqual({ kind: 'none' })
    })

    test.each([
        [{ status: 'failed' as const, error_reason: 'provider_error:Gemini timed out' }, null],
        [
            { status: 'ineligible' as const, error_reason: 'too_short:session is shorter than 5 seconds' },
            'Session is shorter than 5 seconds.',
        ],
        [{ status: 'ineligible' as const }, null],
    ])('a scan that ended without a summary is final, not something to summarize again %#', (ended, reason) => {
        expect(summaryState([observation({ ...ended, scanner_result: null })])).toEqual({ kind: 'failed', reason })
    })

    test('chapters keep their index for the frame endpoint and mark the key moment', () => {
        const state = summaryState([
            observation({
                output: {
                    key_moment_ms: 134_000,
                    chapters: [
                        { kind: 'activity', start_ms: 0, end_ms: 60_000, title: 'Opens files' },
                        { kind: 'idle', start_ms: 60_000, end_ms: 120_000, title: 'Idle' },
                        { kind: 'activity', start_ms: 120_000, end_ms: 252_000, title: 'Share link fails' },
                    ],
                },
                media: [{ kind: 'chapter', position: 2 }],
            }),
        ])
        if (state.kind !== 'ready') {
            throw new Error('expected a summary')
        }
        expect(state.summary.chapters.map((chapter) => [chapter.index, chapter.isKeyMoment, chapter.hasFrame])).toEqual(
            [
                [0, false, false],
                [2, true, true],
            ]
        )
    })

    test('the list puts the feed first, once per session, then the recordings it left out', () => {
        const recordings: RecordingApi[] = [
            { id: 's-2', recording_duration: 60, person: { properties: { email: 'two@example.com' } } },
            { id: 's-1', recording_duration: 252 },
        ]
        const feed: WatchFeedItemApi[] = [
            {
                observation: observation({ session_id: 's-1', output: { title: 'Share fails' } }),
                reason: { kind: 'notable' },
            },
            { observation: observation({ id: 'obs-4', session_id: 's-1' }), reason: { kind: 'recent' } },
        ]
        const rows = sessionListRows(feed, recordings)
        expect(rows.map((item) => [item.sessionId, item.title, item.durationSeconds])).toEqual([
            ['s-1', 'Share fails', 252],
            ['s-2', null, 60],
        ])
    })

    test.each([
        ['134', 134],
        ['12.7', 12],
        ['-1', undefined],
        ['abc', undefined],
        [undefined, undefined],
    ])('parses t=%s', (value, expected) => {
        expect(parseSeekSeconds(value)).toBe(expected)
    })

    test('shares at the linked time, else the key moment, else the start', () => {
        expect(shareSeconds(134_500, 20)).toBe(20)
        expect(shareSeconds(134_500, undefined)).toBe(134)
        expect(shareSeconds(null, undefined)).toBe(0)
    })
})
