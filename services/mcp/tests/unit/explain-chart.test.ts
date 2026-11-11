import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import { ExplainChartInputSchema } from '@/schema/tool-inputs'
import { explainChartHandler } from '@/tools/insights/explainChart'
import { explainChartSaveHandler } from '@/tools/insights/explainChartSave'
import { findStepRange, findStoryRange, lastBucketInProgress } from '@/tools/insights/storyRanges'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

import { insightPageShowsStory } from 'products/product_analytics/mcp/apps/explainChart/storyDisplays'

const DAYS = ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05']
const HOURS = ['2026-10-01 22:00:00', '2026-10-01 23:00:00', '2026-10-02 00:00:00', '2026-10-02 01:00:00']
const WEEKS = ['2026-09-21', '2026-09-28', '2026-10-05']
const MONTHS = ['2025-12-01', '2026-01-01', '2026-02-01']
const QUARTERS = ['2025-10-01', '2026-01-01', '2026-04-01']
const YEARS = ['2024-01-01', '2025-01-01', '2026-01-01']

function apiError(status: number): PostHogApiError {
    return new PostHogApiError({ status, statusText: '', body: '', url: '', method: 'PUT' })
}

const FUNNEL_STEPS = [
    { name: 'Pageview', count: 100, breakdown_value: ['Desktop'] },
    { name: 'Signed up', count: 20, breakdown_value: ['Desktop'] },
    { name: 'Paid', count: 5, breakdown_value: ['Desktop'] },
]
const FUNNEL_STEPS_MOBILE = [
    { name: 'Pageview', count: 40, breakdown_value: ['Mobile'] },
    { name: 'Signed up', count: 4, breakdown_value: ['Mobile'] },
    { name: 'Paid', count: 1, breakdown_value: ['Mobile'] },
]

function inPeriod<Step>(steps: Step[], period: 'current' | 'previous'): (Step & { compare_label: string })[] {
    return steps.map((step) => ({ ...step, compare_label: period }))
}

function createContext(
    query: Record<string, unknown>,
    response: Record<string, unknown> = {},
    saved: unknown = { success: true, data: { id: 'e1' } },
    updated: unknown = { success: false, error: apiError(404) }
): Context {
    return {
        api: {
            insights: vi.fn().mockReturnValue({
                get: vi.fn().mockResolvedValue({
                    success: true,
                    data: { id: 7, short_id: 'abc12345', name: 'Sign-ups', query },
                }),
                saveExplanation: vi.fn().mockResolvedValue(saved),
                updateExplanation: vi.fn().mockResolvedValue(updated),
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

    it('shows the chapters, tells the agent which dates matched no point, and saves nothing', async () => {
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
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('explain-chart-save')
        const { saveExplanation, updateExplanation } = vi.mocked(context.api.insights).mock.results[0]!.value
        expect(saveExplanation).not.toHaveBeenCalled()
        expect(updateExplanation).not.toHaveBeenCalled()
    })

    it.each([
        [
            'the explanation it saved',
            { success: true, data: { id: 'e1' } },
            { success: true, data: { id: 'e2' } },
            'e1',
        ],
        [
            'an id it cannot update',
            { success: false, error: apiError(404) },
            { success: true, data: { id: 'e2' } },
            'e2',
        ],
        [
            'an explanation the server failed to update',
            { success: false, error: apiError(500) },
            { success: true, data: { id: 'e2' } },
            null,
        ],
        [
            'an id it cannot update while saving is throttled',
            { success: false, error: apiError(404) },
            { success: false, error: new Error('Throttled') },
            null,
        ],
    ])('keeps the link when the agent fixes %s', async (_, updated, saved, id) => {
        const context = createContext(
            { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
            {},
            saved,
            updated
        )

        const result = await explainChartSaveHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [{ title: 'A spike on October 2', start: '2026-10-02' }],
            explanationId: '0190a3a4-0000-7000-8000-000000000001',
        })

        expect(result.explanationId).toBe(id)
        expect(result._posthogUrl).toBe(
            id ? `https://us.posthog.com/project/1/insights/abc12345?explanation=${id}` : undefined
        )
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY].includes(`explanationId "${id}"`)).toBe(!!id)
    })

    it('links evidence to its query, insight or GitHub change, and saves no PostHog links', async () => {
        const context = createContext({ kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } })
        const github = 'https://github.com/example/app/pull/12'
        const args = {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [
                {
                    title: 'A spike on October 2',
                    start: '2026-10-02',
                    evidence: [
                        { text: 'From one referrer.', query: { kind: 'TrendsQuery', series: [] } },
                        { text: 'The signup funnel shows it.', insightShortId: 'xyz98765' },
                        { text: 'A release went out.', url: github },
                        { text: 'Raw events agree.', query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
                    ],
                },
            ],
        }

        const result = await explainChartHandler(context, args)

        const shown = result.chapters[0]!.evidence.map((item) => item.url)
        expect(shown[0]).toContain('/project/1/insights/new')
        expect(shown.slice(1, 3)).toEqual(['https://us.posthog.com/project/1/insights/xyz98765', github])
        expect(shown[3]).toContain('/project/1/sql?open_query=')
        await explainChartSaveHandler(context, args)
        const { saveExplanation } = vi.mocked(context.api.insights).mock.results[0]!.value
        const stored = saveExplanation.mock.calls[0][0].data.chapters[0].evidence.map(
            (item: { url: string | null }) => item.url
        )
        expect(stored).toEqual([null, null, github, null])
    })

    it.each([
        ['a step number', '2', undefined, [1, 1]],
        ['the drop between two steps', '1', 'step 3', [0, 2]],
        ['a step name in another case', 'SIGNED UP', undefined, [1, 1]],
        ['a step past the funnel', '4', undefined, null],
        ['steps given backwards', '3', '1', null],
    ] as const)('finds the funnel steps for %s', (_, start, end, expected) => {
        expect(findStepRange(['Pageview', 'Signed up', 'Paid'], start, end)).toEqual(expected)
    })

    it.each([
        ['without a breakdown', FUNNEL_STEPS, 0, [], [100, 20, 5]],
        [
            'following its second breakdown value',
            [FUNNEL_STEPS, FUNNEL_STEPS_MOBILE],
            1,
            ['Desktop', 'Mobile'],
            [40, 4, 1],
        ],
        [
            'following a breakdown value with no text',
            [FUNNEL_STEPS, FUNNEL_STEPS_MOBILE.map((step) => ({ ...step, breakdown_value: [''] }))],
            1,
            ['Desktop', 'None'],
            [40, 4, 1],
        ],
        [
            'compared with the previous period',
            [...inPeriod(FUNNEL_STEPS, 'current'), ...inPeriod(FUNNEL_STEPS, 'previous')],
            0,
            [],
            [100, 20, 5],
        ],
        [
            'with a breakdown, compared with the previous period',
            [
                inPeriod(FUNNEL_STEPS, 'current'),
                inPeriod(FUNNEL_STEPS_MOBILE, 'current'),
                inPeriod(FUNNEL_STEPS, 'previous'),
                inPeriod(FUNNEL_STEPS_MOBILE, 'previous'),
            ],
            1,
            ['Desktop', 'Mobile'],
            [40, 4, 1],
        ],
    ])('explains a funnel %s', async (_, results, series, breakdowns, counts) => {
        const context = createContext(
            { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery', series: [] } },
            { results }
        )

        const result = await explainChartHandler(context, {
            insightId: 'abc12345',
            series,
            headline: 'Most people leave before **Signed up**.',
            chapters: [
                { title: 'The drop to signing up', start: '1', end: '2' },
                { title: 'A step that does not exist', start: '9' },
            ],
        })

        expect(result.shape).toBe('funnel_steps')
        expect(result.shape === 'funnel_steps' && result.steps.map((step) => step.count)).toEqual(counts)
        expect(result.shape === 'funnel_steps' && result.breakdowns).toEqual(breakdowns)
        expect(result.chapters.map((chapter) => chapter.range)).toEqual([[0, 1], null])
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('Use step numbers')
    })

    it.each([
        ['a site other than GitHub', 'https://hackmycomputer.example/pull/1'],
        ['a GitHub file', 'https://github.com/example/app/raw/main/setup.exe'],
    ])('refuses evidence that links to %s', (_, url) => {
        const parsed = ExplainChartInputSchema.safeParse({
            insightId: 'abc12345',
            headline: 'One day stands out.',
            chapters: [{ title: 'A spike', start: '2026-10-02', evidence: [{ text: 'A release.', url }] }],
        })

        expect(parsed.success).toBe(false)
    })

    it.each([
        ['a retention chart', { kind: 'RetentionQuery' }, 'trends charts and funnels that show steps'],
        [
            'a funnel over time',
            { kind: 'FunnelsQuery', series: [], funnelsFilter: { funnelVizType: 'trends' } },
            'conversion over time',
        ],
    ])('refuses %s', async (_, source, message) => {
        const context = createContext({ kind: 'InsightVizNode', source })

        await expect(
            explainChartHandler(context, {
                insightId: 'abc12345',
                series: 0,
                headline: 'Conversion fell.',
                chapters: [{ title: 'A drop', start: '2026-10-02' }],
            })
        ).rejects.toThrow(message)
    })

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
        const result = await call
        expect(context.api.query({ projectId: '1' }).runQuery).toHaveBeenCalledWith({
            query: expect.objectContaining({ trendsFilter: { display: drawnAs } }),
        })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY].includes('explain-chart-save')).toBe(
            insightPageShowsStory(display)
        )
    })

    it('draws each piece of evidence from the query behind it', async () => {
        const series = [{ kind: 'EventsNode', event: 'signed_up' }]
        const sqlResults: Record<string, { columns: string[]; results: unknown[][] }> = {
            by_hour: {
                columns: ['hour', 'browser', 'failures'],
                results: [
                    ['2026-10-02 23:00:00', 'Safari', 4],
                    ['2026-10-03 00:00:00', 'Safari', 9],
                    ['2026-10-03 00:00:00', 'Chrome', 1],
                ],
            },
            by_browser: { columns: ['browser', 'failures'], results: [['Safari', 13]] },
            no_numbers: { columns: ['browser', 'version'], results: [['Safari', '17']] },
            two_metrics: {
                columns: ['hour', 'browser', 'failures', 'requests'],
                results: [['2026-10-02 23:00:00', 'Safari', 4, 10]],
            },
        }
        const context = createContext({ kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } })
        vi.mocked(context.api.query({ projectId: '1' }).runQuery).mockImplementation(
            async ({ query }: { query: Record<string, unknown> }) => {
                if (query.kind !== 'HogQLQuery') {
                    return { results: [{ label: 'signed_up', data: [5, 50, 6, 5, 4], days: DAYS }] }
                }
                const result = sqlResults[query.query as string]
                if (!result) {
                    throw new Error('Unknown column "oops"')
                }
                return result
            }
        )
        const sql = (query: string): Record<string, unknown> => ({ kind: 'HogQLQuery', query })

        const result = await explainChartHandler(context, {
            insightId: 'abc12345',
            series: 0,
            headline: 'One day stands out.',
            chapters: [
                {
                    title: 'A spike on October 2',
                    start: '2026-10-02',
                    evidence: [
                        {
                            text: 'Chrome sent most of it.',
                            query: {
                                kind: 'TrendsQuery',
                                series,
                                breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] },
                            },
                        },
                        {
                            text: 'Safari stayed flat.',
                            query: {
                                kind: 'TrendsQuery',
                                series,
                                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                            },
                        },
                        { text: 'Failures by hour.', query: sql('by_hour') },
                        { text: 'Failures by browser.', query: sql('by_browser') },
                        { text: 'Versions.', query: sql('no_numbers') },
                        { text: 'Two metrics.', query: sql('two_metrics') },
                        { text: 'No kind.', query: { series } },
                        { text: 'A broken query.', query: sql('oops') },
                        { text: 'An unknown kind.', query: { kind: '__proto__' } },
                    ],
                },
            ],
        })

        expect(result.chapters[0]!.evidence.map((item) => [item.queryTool, item.chart, item.url !== null])).toEqual([
            ['query-trends', null, true],
            [null, null, true],
            [
                null,
                {
                    type: 'line',
                    labels: ['Oct 2 23:00', 'Oct 3 00:00'],
                    ticks: ['Oct 2 23:00', 'Oct 3 00:00'],
                    series: [
                        { name: 'Safari', values: [4, 9] },
                        { name: 'Chrome', values: [null, 1] },
                    ],
                    yAxisLabel: 'failures',
                },
                true,
            ],
            [
                null,
                {
                    type: 'bar',
                    labels: ['Safari'],
                    ticks: ['Safari'],
                    series: [{ name: 'failures', values: [13] }],
                    yAxisLabel: 'failures',
                },
                true,
            ],
            [null, null, true],
            [null, null, true],
            ['query-trends', null, true],
            [null, null, true],
            [null, null, true],
        ])
        expect(context.api.query({ projectId: '1' }).runQuery).toHaveBeenCalledWith({
            query: sql('by_hour'),
            signal: expect.any(AbortSignal),
        })
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('"Versions." returned nothing to draw')
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('"Two metrics." returned nothing to draw')
        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain(
            '"A broken query." failed, so it shows as a link only: Unknown column "oops"'
        )
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
