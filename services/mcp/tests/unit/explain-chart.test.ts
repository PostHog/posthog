import { describe, expect, it, vi } from 'vitest'

import { ExplainChartInputSchema } from '@/schema/tool-inputs'
import { explainChartHandler } from '@/tools/insights/explainChart'
import { findStoryRange, lastBucketInProgress } from '@/tools/insights/storyRanges'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

const DAYS = ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05']
const HOURS = ['2026-10-01 22:00:00', '2026-10-01 23:00:00', '2026-10-02 00:00:00', '2026-10-02 01:00:00']
const WEEKS = ['2026-09-21', '2026-09-28', '2026-10-05']
const MONTHS = ['2025-12-01', '2026-01-01', '2026-02-01']
const QUARTERS = ['2025-10-01', '2026-01-01', '2026-04-01']
const YEARS = ['2024-01-01', '2025-01-01', '2026-01-01']

function createContext(query: Record<string, unknown>, response: Record<string, unknown> = {}): Context {
    return {
        api: {
            insights: vi.fn().mockReturnValue({
                get: vi.fn().mockResolvedValue({
                    success: true,
                    data: { id: 7, short_id: 'abc12345', name: 'Sign-ups', query },
                }),
            }),
            query: vi.fn().mockReturnValue({
                runQuery: vi.fn().mockResolvedValue({
                    results: [{ label: 'signed_up', data: [5, 50, 6, 5, 4], days: DAYS }],
                    ...response,
                }),
            }),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context
}

describe('explain-chart', () => {
    it.each([
        ['a day on a daily chart', DAYS, 'day', '2026-10-02', undefined, [1, 1]],
        ['a stretch on a daily chart', DAYS, 'day', '2026-10-02', '2026-10-04', [1, 3]],
        ['a timestamp with a zone on a daily chart', DAYS, 'day', '2026-10-02T00:00:00Z', undefined, [1, 1]],
        ['a day on an hourly chart covers its hours', HOURS, 'hour', '2026-10-02', undefined, [2, 3]],
        ['a date mid-week on a weekly chart', WEEKS, 'week', '2026-10-01', undefined, [1, 1]],
        ['a stretch that starts before the chart', DAYS, 'day', '2026-09-20', '2026-10-02', [0, 1]],
        ['a day after a daily chart ends', DAYS, 'day', '2026-10-09', undefined, null],
        ['a date after the last weekly bucket', WEEKS, 'week', '2026-10-20', undefined, null],
        ['the last day of a short final month', MONTHS, 'month', '2026-02-28', undefined, [2, 2]],
        ['a date after a short final month', MONTHS, 'month', '2026-03-01', undefined, null],
        ['a date mid-quarter on a quarterly chart', QUARTERS, 'quarter', '2026-02-15', undefined, [1, 1]],
        ['a date mid-year on a yearly chart', YEARS, 'year', '2025-06-01', undefined, [1, 1]],
    ] as const)('finds the points for %s', (_, days, interval, start, end, expected) => {
        expect(findStoryRange([...days], interval, start, end)).toEqual(expected)
    })

    it('shows the chapters and tells the agent which dates matched no point', async () => {
        const context = createContext({ kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } })

        const result = await explainChartHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [
                { title: 'A spike on October 2', start: '2026-10-02' },
                { title: 'A gap in November', start: '2026-11-01' },
            ],
        })

        expect(result.chapters.map((chapter) => chapter.range)).toEqual([[1, 1], null])
        expect(result._posthogUrl).toBe('https://us.posthog.com/project/1/insights/abc12345')
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('"A gap in November"')
    })

    it.each([['a funnel', { kind: 'FunnelsQuery', series: [] }, 'only explains trends charts']])(
        'refuses %s',
        async (_, source, message) => {
            const context = createContext({ kind: 'InsightVizNode', source })

            await expect(
                explainChartHandler(context, {
                    insightId: 'abc12345',
                    series: 0,
                    headline: 'Conversion fell.',
                    chapters: [{ title: 'A drop', start: '2026-10-02' }],
                })
            ).rejects.toThrow(message)
        }
    )

    it.each([
        ...[
            'ActionsLineGraph',
            'ActionsLineGraphCumulative',
            'ActionsBar',
            'ActionsUnstackedBar',
            'ActionsAreaGraph',
            'ActionsStackedBar',
        ].map((display) => [display, display] as const),
        ...[
            'Auto',
            'BoldNumber',
            'Metric',
            'ActionsPie',
            'ActionsDonut',
            'ActionsProportionBar',
            'ActionsBarValue',
            'ActionsTable',
            'WorldMap',
            'CalendarHeatmap',
            'SlopeGraph',
        ].map((display) => [display, 'ActionsLineGraph'] as const),
        ...['BoxPlot', 'TwoDimensionalHeatmap', 'ScatterPlot', 'SomeFutureDisplay'].map(
            (display) => [display, null] as const
        ),
    ])('handles a %s chart', async (display, drawnAs) => {
        const context = createContext({
            kind: 'InsightVizNode',
            source: { kind: 'TrendsQuery', series: [], trendsFilter: { display } },
        })
        const call = explainChartHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [{ title: 'A spike on October 2', start: '2026-10-02' }],
        })

        if (drawnAs === null) {
            await expect(call).rejects.toThrow('one value over time')
            return
        }
        await call
        expect(context.api.query({ projectId: '1' }).runQuery).toHaveBeenCalledWith({
            query: expect.objectContaining({ trendsFilter: { display: drawnAs } }),
        })
    })

    const hitRate = {
        type: 'line' as const,
        labels: ['20:00', '21:00'],
        series: [{ name: 'hit rate', values: [0.9, 0.55] }],
    }

    it('keeps a chart only for evidence that query-trends can draw again', async () => {
        const series = [{ kind: 'EventsNode', event: 'signed_up' }]
        const drawable = {
            kind: 'TrendsQuery',
            series,
            breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] },
        }
        const linkOnly = {
            kind: 'TrendsQuery',
            series,
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        }
        const context = createContext({ kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } })

        const result = await explainChartHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [
                {
                    title: 'A spike on October 2',
                    start: '2026-10-02',
                    evidence: [
                        { text: 'Chrome sent most of it.', query: drawable },
                        { text: 'Safari stayed flat.', query: linkOnly },
                        {
                            text: 'The hit rate fell.',
                            query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                            chart: hitRate,
                        },
                    ],
                },
            ],
        })

        expect(
            result.chapters[0]!.evidence.map((item) => [item.query !== null, item.chart ?? null, item.url !== null])
        ).toEqual([
            [true, null, true],
            [false, null, true],
            [false, hitRate, true],
        ])
    })

    it('refuses a chart whose series do not have one value per label', () => {
        const parsed = ExplainChartInputSchema.safeParse({
            insightId: 'abc12345',
            headline: 'One day stands out.',
            chapters: [
                {
                    title: 'A spike on October 2',
                    start: '2026-10-02',
                    evidence: [{ text: 'The hit rate fell.', chart: { ...hitRate, labels: ['20:00'] } }],
                },
            ],
        })

        expect(parsed.success).toBe(false)
    })

    it.each([
        ['a day that is still running', ['2026-10-17', '2026-10-18'], 'day', 'UTC', '2026-10-18T10:00:00Z', true],
        ['a day that has ended', ['2026-10-16', '2026-10-17'], 'day', 'UTC', '2026-10-18T10:00:00Z', false],
        [
            'a day still running west of Greenwich',
            ['2026-10-17'],
            'day',
            'America/Los_Angeles',
            '2026-10-18T03:00:00Z',
            true,
        ],
        ['a month that is still running', ['2026-09-01', '2026-10-01'], 'month', 'UTC', '2026-10-18T10:00:00Z', true],
        [
            'a quarter that is still running',
            ['2026-07-01', '2026-10-01'],
            'quarter',
            'UTC',
            '2026-10-23T10:00:00Z',
            true,
        ],
        [
            'a day still running on the night the clocks change',
            ['2026-09-26'],
            'day',
            'Pacific/Auckland',
            '2026-09-26T11:30:00Z',
            true,
        ],
    ] as const)('knows whether the last point is complete for %s', (_, days, interval, timezone, now, expected) => {
        expect(lastBucketInProgress([...days], interval, timezone, Date.parse(now))).toBe(expected)
    })

    it('draws a slope or number chart as a line chart and passes the query warnings on', async () => {
        const context = createContext(
            { kind: 'TrendsQuery', series: [], trendsFilter: { display: 'SlopeGraph' } },
            { warnings: [{ type: 'stale', message: 'Warehouse data is 3 days old.' }] }
        )

        const result = await explainChartHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [{ title: 'A spike on October 2', start: '2026-10-02' }],
        })

        expect(context.api.query({ projectId: '1' }).runQuery).toHaveBeenCalledWith({
            query: expect.objectContaining({ trendsFilter: { display: 'ActionsLineGraph' } }),
        })
        expect(result.warnings).toEqual([{ type: 'stale', message: 'Warehouse data is 3 days old.' }])
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('Warehouse data is 3 days old.')
    })
})
