import type { ReplayObservationApi } from '../generated/api.schemas'
import { recordingTimeline, timelineRows } from './recordingTimeline'

function summary(
    output: Record<string, unknown> | null,
    status: ReplayObservationApi['status'] = 'succeeded',
    createdAt = '2026-10-02T09:00:00Z',
    id = 'summary-1'
): ReplayObservationApi {
    return {
        id,
        status,
        created_at: createdAt,
        scanner_snapshot: { scanner_type: 'summarizer', name: 'Summary' },
        scanner_result: output ? { model_output: { scanner_type: 'summarizer', ...output } } : null,
        media: [],
    } as unknown as ReplayObservationApi
}

function monitor(id: string, keyMomentMs: number | null, verdict = 'yes'): ReplayObservationApi {
    return {
        id,
        status: 'succeeded',
        created_at: '2026-10-02T09:05:00Z',
        scanner_snapshot: { scanner_type: 'monitor', name: id },
        scanner_result: { model_output: { scanner_type: 'monitor', verdict, key_moment_ms: keyMomentMs } },
        media: [],
    } as unknown as ReplayObservationApi
}

const chapter = (start: number, end: number, title: string, kind = 'activity'): Record<string, unknown> => ({
    kind,
    start_ms: start,
    end_ms: end,
    title,
})

describe('recordingTimeline', () => {
    it.each<{
        name: string
        observations: ReplayObservationApi[]
        state: string
        chapters: number
        markers: number
        inactive?: number
    }>([
        { name: 'only scans', observations: [monitor('m1', 5_000)], state: 'none', chapters: 0, markers: 1 },
        {
            name: 'a summary still running',
            observations: [summary(null, 'running'), monitor('m1', 5_000)],
            state: 'pending',
            chapters: 0,
            markers: 1,
        },
        {
            name: 'a summary from before chapters existed',
            observations: [summary({ title: 't' })],
            state: 'outdated',
            chapters: 0,
            markers: 0,
        },
        {
            name: 'a summary from before inactive periods, whose idle chapters become gaps',
            observations: [
                summary({
                    chapters: [
                        chapter(0, 10_000, 'A'),
                        chapter(10_000, 70_000, 'Idle', 'idle'),
                        chapter(70_000, 80_000, 'B'),
                    ],
                }),
            ],
            state: 'ready',
            chapters: 2,
            markers: 0,
            inactive: 1,
        },
        {
            name: 'a summary with chapters, and a scan without a key moment',
            observations: [summary({ chapters: [chapter(0, 10_000, 'A')] }), monitor('m1', null)],
            state: 'ready',
            chapters: 1,
            markers: 0,
        },
    ])('reads the state of $name', ({ observations, state, chapters, markers, inactive = 0 }) => {
        const timeline = recordingTimeline(observations)
        expect([
            timeline.summaryState,
            timeline.chapters.length,
            timeline.markers.length,
            timeline.inactive.length,
        ]).toEqual([state, chapters, markers, inactive])
    })

    it.each<{ name: string; observations: ReplayObservationApi[]; durationMs: number | null; expected: string[] }>([
        {
            name: 'scans without a timeline leave the rail empty',
            observations: [monitor('m1', 5_000)],
            durationMs: 60_000,
            expected: [],
        },
        {
            name: 'a timeline sits between the session start and end',
            observations: [summary({ chapters: [chapter(0, 10_000, 'A')] }), monitor('m1', 5_000)],
            durationMs: 60_000,
            expected: ['boundary start', 'chapter', 'boundary end'],
        },
        {
            name: 'a recording that loads shorter than its chapters still ends after them',
            observations: [summary({ chapters: [chapter(0, 90_000, 'A')] })],
            durationMs: 60_000,
            expected: ['boundary start', 'chapter', 'boundary end 90000'],
        },
        {
            name: 'an idle stretch that starts inside a chapter begins where the chapter ends',
            observations: [
                summary({
                    chapters: [chapter(0, 20_000, 'A'), chapter(90_000, 100_000, 'B')],
                    inactive_periods: [{ start_ms: 10_000, end_ms: 90_000 }],
                }),
            ],
            durationMs: 100_000,
            expected: ['boundary start', 'chapter', 'inactive 20000', 'chapter', 'boundary end'],
        },
        {
            name: 'an unknown length leaves out the end',
            observations: [summary({ chapters: [chapter(0, 10_000, 'A')] })],
            durationMs: null,
            expected: ['boundary start', 'chapter'],
        },
    ])('$name', ({ observations, durationMs, expected }) => {
        const rows = timelineRows(recordingTimeline(observations), durationMs)
        expect(
            rows.map((row) =>
                row.kind === 'inactive'
                    ? `inactive ${row.startMs}`
                    : row.kind !== 'boundary'
                      ? row.kind
                      : row.edge === 'end' && row.atMs !== durationMs
                        ? `boundary end ${row.atMs}`
                        : `boundary ${row.edge}`
            )
        ).toEqual(expected)
    })

    it('uses the newest succeeded summary', () => {
        const older = summary({ chapters: [chapter(0, 10_000, 'Old')] }, 'succeeded', '2026-10-01T09:00:00Z', 'old')
        const newer = summary({ chapters: [chapter(0, 10_000, 'New')] }, 'succeeded', '2026-10-02T09:00:00Z', 'new')
        expect(recordingTimeline([older, newer]).chapters.map((c) => c.title)).toEqual(['New'])
    })

    it('lays chapters and long idle out in time order, skipping idle chapters and short pauses', () => {
        const observations = [
            summary({
                chapters: [
                    chapter(0, 20_000, 'Browses'),
                    chapter(20_000, 30_000, 'Idle', 'idle'),
                    chapter(90_000, 120_000, 'Buys'),
                ],
                inactive_periods: [
                    { start_ms: 20_000, end_ms: 90_000 },
                    { start_ms: 100_000, end_ms: 105_000 },
                ],
            }),
            monitor('in-gap', 50_000),
        ]
        const timeline = recordingTimeline(observations)
        const rows = timelineRows(timeline).map((row) =>
            row.kind === 'chapter'
                ? `chapter ${row.chapter.title}`
                : row.kind === 'inactive'
                  ? `inactive ${row.startMs}-${row.endMs}`
                  : `boundary ${row.edge}`
        )
        expect(rows).toEqual(['boundary start', 'chapter Browses', 'inactive 20000-90000', 'chapter Buys'])
        expect(timeline.chapters.find((c) => c.title === 'Buys')?.inactiveMs).toBe(5_000)
    })
})
