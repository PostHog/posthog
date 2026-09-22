import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'
import { axisDays, groupTimelines, redTimeByCause } from './pullRequestDayView'

const HOUR = 3600 * 1000
const T0 = Date.parse('2026-07-01T10:00:00Z')

function at(hours: number): string {
    return new Date(T0 + hours * HOUR).toISOString()
}

function pr(
    number: number,
    segments: [Kind, number, number][],
    options: { merged?: boolean; draft?: boolean } = {}
): PRTimelineApi {
    const last = segments[segments.length - 1]
    return {
        number,
        title: `PR ${number}`,
        author: { handle: 'alice', display_name: 'alice', avatar_url: '', is_bot: false },
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        state: options.merged ? 'merged' : 'open',
        is_draft: !!options.draft,
        created_at: at(segments[0][1]),
        started_at: at(segments[0][1]),
        merged_at: options.merged ? at(last[2]) : null,
        pushes: [],
        estimated_cost_usd: null,
        billable_minutes: null,
        segments: segments.map(([kind, start, end]) => ({ kind, started_at: at(start), ended_at: at(end) })),
    }
}

describe('pullRequestDayView', () => {
    it('orders groups by what the author can act on first', () => {
        const groups = groupTimelines([
            pr(1, [
                [Kind.CiRunning, 0, 1],
                [Kind.MergeQueue, 1, 5],
            ]),
            pr(2, [
                [Kind.WaitingForReview, 0, 2],
                [Kind.OutOfMergeQueue, 2, 3],
            ]),
            pr(3, [[Kind.WaitingForReview, 0, 60]], { merged: true }),
            pr(4, [
                [Kind.CiRunning, 0, 1],
                [Kind.ApprovedNotEnqueued, 1, 30],
            ]),
            pr(
                5,
                [
                    [Kind.WaitingForReview, 0, 2],
                    [Kind.RedFixedByPush, 2, 3],
                ],
                { merged: true }
            ),
            pr(6, [[Kind.Draft, 0, 8]], { draft: true }),
        ])

        expect(groups.map((group) => [group.label, group.rows.map((row) => row.pr.number)])).toEqual([
            ["Open, the author's move", [4, 2]],
            ['Open, waiting on others', [1]],
            ['Merged, took over 2 days', [3]],
            ['Merged, under a day', [5]],
            ['Open, still draft', [6]],
        ])
        // A merged row explains itself by the state that took longest, not the last one.
        expect(groups[3].rows[0].highlightKind).toBe(Kind.WaitingForReview)
    })

    // Without the p90 pick the 1000-hour row would push the axis to the 14-day cap. The bound is 2
    // rather than 1 because the row origin is the local 06:00 at or before the start, which sits up
    // to 23 hours earlier depending on the timezone Jest runs in.
    it('one outlier does not stretch the axis', () => {
        const lengths = [5, 6, 7, 8, 9, 10, 11, 12, 13, 1000]
        const items = lengths.map((length, index) => pr(index, [[Kind.CiRunning, 0, length]], { merged: true }))
        expect(axisDays(items, 'days')).toBeLessThanOrEqual(2)
    })

    it.each([
        ['weeks round up to a whole week', 'weeks', [5, 20, 30], 7],
        ['long waits cap at two weeks', 'days', [400, 500, 600], 14],
    ] as const)('%s', (_name, alignment, lengths, expectedDays) => {
        const items = lengths.map((length, index) => pr(index, [[Kind.CiRunning, 0, length]], { merged: true }))
        expect(axisDays(items, alignment)).toBe(expectedDays)
    })

    it('averages red time by cause over merged pull requests only', () => {
        const red = redTimeByCause([
            pr(
                1,
                [
                    [Kind.CiRunning, 0, 1],
                    [Kind.RedPassedOnRerun, 1, 3],
                ],
                { merged: true }
            ),
            pr(2, [[Kind.WaitingForReview, 0, 4]], { merged: true }),
            pr(3, [[Kind.RedNotProvable, 0, 50]]),
        ])

        expect(red.mergedCount).toBe(2)
        expect(red.totalSecondsPerMergedPr).toBe(3600)
        expect(red.secondsPerMergedPr.find((entry) => entry.kind === Kind.RedPassedOnRerun)?.seconds).toBe(3600)
    })
})
