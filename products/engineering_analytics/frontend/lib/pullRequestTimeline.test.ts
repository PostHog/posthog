import { PRTimelineApi, PRTimelineSegmentKindEnumApi as Kind } from '../generated/api.schemas'
import { dayStartsBetween } from './pullRequestDayView'
import { timeInStates, timelineMilestones, trackAxis } from './pullRequestTimeline'

const HOUR = 3600 * 1000
// jest runs in UTC.
const T0 = Date.parse('2026-07-01T10:00:00Z')

function at(hours: number): string {
    return new Date(T0 + hours * HOUR).toISOString()
}

function pr(
    segments: [Kind, number, number][],
    options: { state?: PRTimelineApi['state']; draft?: boolean; openedAtStart?: boolean } = {}
): PRTimelineApi {
    const state = options.state ?? 'open'
    return {
        number: 7,
        title: 'PR 7',
        author: { handle: 'alice', display_name: 'alice', avatar_url: '', is_bot: false },
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        state,
        is_draft: !!options.draft,
        created_at: at(segments[0][1] - (options.openedAtStart ? 0 : 1)),
        started_at: at(segments[0][1]),
        merged_at: state === 'merged' ? at(segments[segments.length - 1][2]) : null,
        pushes: 1,
        estimated_cost_usd: null,
        billable_minutes: null,
        segments: segments.map(([kind, start, end]) => ({ kind, started_at: at(start), ended_at: at(end) })),
    }
}

describe('pullRequestTimeline', () => {
    it('groups time by who can move the pull request on, longest state first', () => {
        const { wholeSeconds, groups, longest } = timeInStates(
            pr(
                [
                    [Kind.CiRunning, 0, 1],
                    [Kind.WaitingForReview, 1, 5],
                    [Kind.ApprovedNotEnqueued, 5, 6],
                    [Kind.CiRunning, 6, 7],
                    [Kind.RedFixedByPush, 7, 9],
                    [Kind.MergeQueue, 9, 10],
                ],
                { state: 'merged' }
            )
        )

        expect(wholeSeconds).toBe(10 * 3600)
        expect(groups.map((group) => [group.label, group.share])).toEqual([
            ['Reviewers', 0.4],
            ['Author', 0.3],
            ['CI and merge queue', 0.3],
        ])
        expect(groups[1].states.map((state) => state.kind)).toEqual([Kind.RedFixedByPush, Kind.ApprovedNotEnqueued])
        expect(groups[2].states.map((state) => [state.kind, state.seconds])).toEqual([
            [Kind.CiRunning, 2 * 3600],
            [Kind.MergeQueue, 3600],
        ])
        expect(longest).toEqual({ kind: Kind.WaitingForReview, seconds: 4 * 3600, share: 0.4 })
    })

    it('marks pushes after the start, the queue dropping the pull request, and the merge, in time order', () => {
        const merged = pr(
            [
                [Kind.WaitingForReview, 0, 4],
                [Kind.MergeQueue, 4, 5],
            ],
            { state: 'merged' }
        )
        const pushes = [
            { headSha: 'aaaaaaaaaa', at: at(-2) },
            { headSha: 'bbbbbbbbbb', at: at(0) },
            { headSha: 'cccccccccc', at: at(2) },
            { headSha: 'dddddddddd', at: at(6) },
        ]

        expect(timelineMilestones(merged, pushes).map((milestone) => milestone.label)).toEqual([
            'Ready for review',
            'Push ccccccc',
            'Merged',
        ])

        const kicked = pr([
            [Kind.MergeQueue, 0, 2],
            [Kind.OutOfMergeQueue, 2, 3],
        ])
        expect(timelineMilestones(kicked, [{ headSha: 'eeeeeeeeee', at: at(1) }])).toEqual([
            { kind: 'start', at: at(0), label: 'Ready for review' },
            { kind: 'push', at: at(1), label: 'Push eeeeeee' },
            { kind: 'out_of_queue', at: at(2), label: 'Out of the merge queue' },
        ])
    })

    it.each([
        ['went ready after it opened', { state: 'closed' as const }, 'Ready for review', 'Closed'],
        [
            'starts at opening with no ready event',
            { state: 'closed' as const, openedAtStart: true },
            'Opened',
            'Closed',
        ],
        ['is an open draft', { draft: true, openedAtStart: true }, 'Opened', undefined],
    ])('labels the ends of a pull request that %s', (_, options, startLabel, endLabel) => {
        const milestones = timelineMilestones(pr([[Kind.Draft, 0, 3]], options), [])

        expect(milestones[0].label).toBe(startLabel)
        expect(milestones.length > 1 ? milestones[milestones.length - 1].label : undefined).toBe(endLabel)
    })

    it('starts the axis at the day start before a small-hours start, so that night is shaded', () => {
        const axis = trackAxis(
            pr([[Kind.WaitingForReview, -7, 30]]) // 03:00 on Wednesday to 16:00 on Thursday
        )
        const dayStarts = dayStartsBetween(axis.fromMs, axis.toMs)

        expect(dayStarts.map((day) => day.toISOString())).toEqual([
            '2026-06-30T06:00:00.000Z',
            '2026-07-01T06:00:00.000Z',
            '2026-07-02T06:00:00.000Z',
        ])
        expect(dayStarts[0].valueOf()).toBeLessThanOrEqual(axis.fromMs)
    })
})
