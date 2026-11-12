import type { insightLogicValues } from 'scenes/insights/insightLogic'

import type {
    ExplainChartData,
    FunnelStepsExplainChartData,
    TimeSeriesExplainChartData,
} from 'products/product_analytics/mcp/apps/explainChart/explainChartTypes'
import { followedSeriesIndex } from 'products/product_analytics/mcp/apps/explainChart/storySeries'

import {
    explainChartStoryFor,
    followedFunnelBarIndex,
    funnelStoryOnChart,
    storyOnChart,
    withEvidenceLinks,
} from './explainChartStory'

const INSIGHT = { id: 42, short_id: 'aBc12345' } as insightLogicValues['insight']
const STORY = {
    shape: 'time_series',
    query: { kind: 'TrendsQuery' },
    results: [{ label: 'Pageviews', data: [1, 2, 3], days: ['2026-10-01', '2026-10-02', '2026-10-03'] }],
    seriesIndex: 0,
    insightName: 'Pageviews',
    lastPointInProgress: false,
    headline: 'A peak on **October 2**.',
    chapters: [],
}
const FUNNEL_STORY = {
    shape: 'funnel_steps',
    query: { kind: 'FunnelsQuery' },
    steps: [
        { name: 'Pageview', count: 100 },
        { name: 'Signed up', count: 20 },
    ],
    breakdowns: [],
    seriesIndex: 0,
    insightName: 'Signups',
    headline: 'Most people leave before **Signed up**.',
    chapters: [],
}

describe('explainChartStory', () => {
    test.each([
        ['the short id', { insightId: 'aBc12345' }, STORY, STORY],
        ['the numeric id under an alias', { id: 42 }, STORY, STORY],
        ['another insight', { insightId: 'zzz99999' }, STORY, null],
        ['an unsaved query', { query: { kind: 'TrendsQuery' } }, STORY, null],
        ['a result that is not a story', { insightId: 'aBc12345' }, { headline: 'A peak' }, null],
        [
            'a story from a server that predates shapes',
            { insightId: 'aBc12345' },
            { ...STORY, shape: undefined },
            STORY,
        ],
        ['a funnel story', { insightId: 'aBc12345' }, FUNNEL_STORY, FUNNEL_STORY],
        [
            'a story of a shape this page cannot draw',
            { insightId: 'aBc12345' },
            { ...STORY, shape: 'retention_grid' },
            null,
        ],
    ])('takes a story for %s only when it explains this insight', (_, input, output, expected) => {
        expect(explainChartStoryFor(INSIGHT, input, output)).toEqual(expected)
    })

    test.each([
        [
            'the chart moved on a day',
            [{ label: 'Pageviews', days: ['2026-10-02', '2026-10-03', '2026-10-04'] }],
            0,
            [
                [0, 0],
                [1, 1],
            ],
        ],
        [
            'the chart moved past a chapter',
            [{ label: 'Pageviews', days: ['2026-10-03', '2026-10-04', '2026-10-05'] }],
            0,
            [null, [0, 0]],
        ],
        [
            'the chart is unchanged',
            [{ label: 'Pageviews', days: ['2026-10-01', '2026-10-02', '2026-10-03'] }],
            0,
            [
                [1, 1],
                [2, 2],
            ],
        ],
        [
            'another series overtook the followed one',
            [
                { label: 'Signups', days: ['2026-10-01', '2026-10-02', '2026-10-03'] },
                { label: 'Pageviews', days: ['2026-10-01', '2026-10-02', '2026-10-03'] },
            ],
            1,
            [
                [1, 1],
                [2, 2],
            ],
        ],
        [
            'the followed series is gone',
            [{ label: 'Signups', days: ['2026-10-01', '2026-10-02', '2026-10-03'] }],
            0,
            [null, null],
        ],
    ])('keeps each chapter on its saved date when %s', (_, chart, expectedIndex, expected) => {
        const story = {
            ...STORY,
            chapters: [
                { title: 'A peak', range: [1, 1] },
                { title: 'A dip', range: [2, 2] },
            ],
        } as unknown as TimeSeriesExplainChartData

        const shown = storyOnChart(story, chart, followedSeriesIndex(story, chart), false)

        expect(shown.seriesIndex).toBe(expectedIndex)
        expect(shown.chapters.map((chapter) => chapter.range)).toEqual(expected)
    })

    test.each([
        [
            'the chart draws a baseline before the breakdown values',
            ['Baseline', ['Desktop'], ['Mobile']],
            'Mobile',
            2,
            [50, 5],
        ],
        ['the chart hides the followed breakdown value', ['Baseline', ['Desktop']], 'Mobile', null, [40, 4]],
        ['the followed breakdown value has no text', ['Baseline', [''], ['Mobile']], 'None', 1, [30, 3]],
    ])('follows a funnel breakdown value by its name when %s', (_, drawn, followed, expectedBar, expectedCounts) => {
        const counts: Record<string, number[]> = {
            Baseline: [150, 25],
            Desktop: [100, 20],
            Mobile: [50, 5],
            '': [30, 3],
        }
        const chart = [0, 1].map((step) => ({
            count: counts.Baseline[step],
            nested_breakdown: drawn.map((value) => ({ breakdown_value: value, count: counts[String(value)][step] })),
        }))
        const story = {
            ...FUNNEL_STORY,
            steps: [
                { name: 'Pageview', count: 40 },
                { name: 'Signed up', count: 4 },
            ],
            breakdowns: ['Another value', followed],
            seriesIndex: 1,
            chapters: [{ title: 'The drop to signing up', range: [0, 1] }],
        } as unknown as FunnelStepsExplainChartData

        const bar = followedFunnelBarIndex(story, chart)
        const shown = funnelStoryOnChart(story, chart, bar)

        expect(bar).toBe(expectedBar)
        expect(shown.steps.map((step) => step.count)).toEqual(expectedCounts)
        expect(shown.chapters.map((chapter) => chapter.range)).toEqual([expectedBar === null ? null : [0, 1]])
    })

    it('links saved evidence to its query, its insight or its GitHub change', () => {
        const story = {
            ...STORY,
            chapters: [
                {
                    title: 'A peak',
                    range: [1, 1],
                    summary: null,
                    cause: null,
                    confidence: null,
                    confidenceReason: null,
                    evidence: [
                        {
                            text: 'From one referrer.',
                            query: { kind: 'TrendsQuery', series: [] },
                            url: 'https://us.posthog.com/project/1/insights/new',
                        },
                        { text: 'The signup funnel shows it.', insightShortId: 'xyz98765' },
                        { text: 'Shipped in a release.', url: 'https://github.com/example/app/pull/1' },
                        { text: 'Seen in the logs.' },
                    ],
                },
            ],
        } as unknown as ExplainChartData

        const [withQuery, withInsight, withLink, withNothing] = withEvidenceLinks(story).chapters[0].evidence

        expect(withQuery.url).toMatch(/^\/insights\/new/)
        expect(decodeURIComponent(withQuery.url ?? '')).toContain('"kind":"InsightVizNode"')
        expect(withInsight.url).toBe('/insights/xyz98765')
        expect(withLink.url).toBe('https://github.com/example/app/pull/1')
        expect(withNothing.url).toBeNull()
    })
})
