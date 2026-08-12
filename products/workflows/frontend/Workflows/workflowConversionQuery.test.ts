import api from 'lib/api'

import { PropertyFilterType } from '~/types'

import { buildConversionGoalStep, loadWorkflowConversionSeries } from './workflowConversionQuery'

const eventGoal = (...ids: string[]): any => ({
    window_minutes: null,
    filters: [],
    events: [{ filters: { events: ids.map((id) => ({ id, type: 'events' })) } }],
})

describe('workflowConversionQuery', () => {
    let query: jest.SpyInstance

    const baseRequest = {
        workflowId: 'flow-1',
        dateFrom: '2026-01-01T00:00:00.000Z',
        dateTo: '2026-01-03T00:00:00.000Z',
        interval: 'day' as const,
        windowMinutes: null,
        conversion: eventGoal('purchase'),
    }

    // The funnel answers with a rate per bucket, the trends query with the entrants in each.
    const mockQueries = (
        funnel: { days: string[]; data: number[] },
        entrants: { days: string[]; data: number[] }
    ): void => {
        query.mockImplementation(async (q: any) =>
            q.kind === 'FunnelsQuery' ? { results: [funnel] } : { results: [entrants] }
        )
    }

    beforeEach(() => {
        query = jest.spyOn(api, 'query')
        mockQueries(
            { days: ['2026-01-01', '2026-01-02'], data: [25, 50] },
            { days: ['2026-01-01', '2026-01-02'], data: [4, 6] }
        )
    })

    afterEach(() => {
        query.mockRestore()
    })

    // A goal naming two events means "either one converts them". AND-ing them instead matches nothing,
    // which reads as 0% rather than as an error, the same silent-zero failure this metric already had.
    it('ORs the goal events so any one of them converts', () => {
        const step = buildConversionGoalStep(eventGoal('purchase', 'subscribed'), 'flow-1')

        // Unnamed step: the identity is a condition, because a funnel step names at most one event.
        expect(step?.event).toBeNull()
        expect(step?.properties).toEqual([
            { type: PropertyFilterType.HogQL, key: "event = 'purchase' OR event = 'subscribed'" },
        ])
    })

    // A single-event goal is the shape the editor produces by default, and it round-trips exactly:
    // naming the event keeps the step readable and leaves its own filters untouched.
    it('names the event when the goal has only one', () => {
        const step = buildConversionGoalStep(eventGoal('purchase'), 'flow-1')

        expect(step?.event).toBe('purchase')
        expect(step?.properties).toEqual([])
    })

    // Property-based goals are only ever recorded as a $workflows_conversion event, so dropping that
    // branch would silently zero every property goal.
    it('matches property goals on the conversion event', () => {
        const step = buildConversionGoalStep(
            { window_minutes: null, filters: [{ key: 'plan', value: 'paid' }] } as any,
            'flow-1'
        )

        expect(step?.properties?.[0]).toEqual({
            type: PropertyFilterType.HogQL,
            key: "(event = '$workflows_conversion' AND properties.$workflow_id = 'flow-1' AND properties.$workflow_conversion_type = 'property')",
        })
    })

    it.each([
        ['no goal at all', undefined],
        ['a goal whose event list is empty', { window_minutes: null, filters: [], events: [{ filters: {} }] }],
    ])('returns no properties for %s', (_name, conversion) => {
        expect(buildConversionGoalStep(conversion as any, 'flow-1')).toBeNull()
    })

    // The two queries are separate, so the conversions have to be read off the rate for the bucket
    // they belong to. Pairing them positionally instead would misattribute every bucket as soon as
    // the funnel's widened range gives it more days than the entrant series.
    it('pairs each bucket rate with that bucket entrants', async () => {
        const result = await loadWorkflowConversionSeries(baseRequest, 'UTC')

        expect(result.labels).toEqual(['2026-01-01', '2026-01-02'])
        expect(result.enrolled).toEqual([4, 6])
        expect(result.converted).toEqual([1, 3])
    })

    it('counts no conversions for a bucket the funnel did not return', async () => {
        mockQueries({ days: ['2026-01-02'], data: [50] }, { days: ['2026-01-01', '2026-01-02'], data: [4, 6] })

        expect((await loadWorkflowConversionSeries(baseRequest, 'UTC')).converted).toEqual([0, 3])
    })

    // The executor stamps a property conversion with the same timestamp as the enrollment, so a
    // funnel scores every one of those runs as unconverted and the tile reads 0%. Property-only goals
    // have to pair on the run id instead.
    it('counts a property-only goal by pairing on the run id, not with a funnel', async () => {
        const queryHogQL = jest
            .spyOn(api, 'queryHogQL')
            .mockResolvedValue({ results: [['2026-01-02T00:00:00Z', 3, 1]] } as any)

        const result = await loadWorkflowConversionSeries(
            { ...baseRequest, conversion: { window_minutes: null, filters: [{ key: 'plan' }] } as any },
            'UTC'
        )

        expect(query).not.toHaveBeenCalled()
        expect(result.enrolled).toEqual([3])
        expect(result.converted).toEqual([1])
        queryHogQL.mockRestore()
    })

    it('skips the query when the workflow has no conversion goal', async () => {
        const result = await loadWorkflowConversionSeries({ ...baseRequest, conversion: undefined }, 'UTC')

        expect(query).not.toHaveBeenCalled()
        expect(result).toEqual({ labels: [], enrolled: [], converted: [] })
    })

    // The funnel range is widened by the window so late conversions still count, which also gives it
    // buckets past the range. Those must not reach the chart as days the user did not ask for.
    it('drops funnel buckets past the requested range', async () => {
        mockQueries({ days: ['2026-01-02', '2026-01-09'], data: [50, 0] }, { days: ['2026-01-02'], data: [6] })

        expect((await loadWorkflowConversionSeries(baseRequest, 'UTC')).labels).toEqual(['2026-01-02'])
    })

    // The funnel gets the widened end date, the entrant count the one that was asked for.
    it('asks the funnel past the range but counts entrants only inside it', async () => {
        await loadWorkflowConversionSeries({ ...baseRequest, windowMinutes: 60 }, 'UTC')

        const funnel = query.mock.calls.find((c: any[]) => c[0].kind === 'FunnelsQuery')![0]
        const entrants = query.mock.calls.find((c: any[]) => c[0].kind === 'TrendsQuery')![0]
        expect(funnel.dateRange.date_to).toBe('2026-01-03T01:00:00.000Z')
        expect(entrants.dateRange.date_to).toBe(baseRequest.dateTo)
    })

    // A goal with no window converts however long after. Passing 0 or nothing would fall back to the
    // funnel's own 14-day default and quietly stop counting later conversions.
    it.each([
        ['a set window', 60, 60],
        ['no window', null, 365 * 24 * 60],
    ])('uses %s as the funnel conversion window', async (_name, windowMinutes, expected) => {
        await loadWorkflowConversionSeries({ ...baseRequest, windowMinutes }, 'UTC')

        const funnel = query.mock.calls.find((c: any[]) => c[0].kind === 'FunnelsQuery')![0]
        expect(funnel.funnelsFilter).toMatchObject({
            funnelWindowInterval: expected,
            funnelWindowIntervalUnit: 'minute',
        })
    })
})
