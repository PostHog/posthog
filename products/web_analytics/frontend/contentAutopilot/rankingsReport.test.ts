import type { AEOPromptSetRankingsApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_SET_RANKINGS } from './contentAutopilotStoryFixtures'
import { rankingsChart } from './rankingsReport'

describe('rankingsReport', () => {
    it('starts at the first day with answers and breaks the line of a brand on a day it has no value', () => {
        const rankings: AEOPromptSetRankingsApi = {
            ...EXAMPLE_PROMPT_SET_RANKINGS,
            window_from: '2026-10-01',
            window_to: '2026-10-06',
            brands: EXAMPLE_PROMPT_SET_RANKINGS.brands.slice(0, 2),
            daily: [
                // Days without answers have no visibility, so they are gaps and never read 0%.
                { date: '2026-10-02', domain: 'example.com', answers: 0, visibility: null },
                { date: '2026-10-03', domain: 'example.com', answers: 4, visibility: 0.5 },
                { date: '2026-10-05', domain: 'example.com', answers: 4, visibility: 0.25 },
                { date: '2026-10-04', domain: 'rival.example.org', answers: 4, visibility: 0.75 },
            ],
        }

        const chart = rankingsChart(rankings)

        expect(chart.labels).toEqual(['2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06'])
        expect(chart.series.map((series) => [series.domain, series.data])).toEqual([
            ['example.com', [0.5, NaN, 0.25, NaN]],
            ['rival.example.org', [NaN, 0.75, NaN, NaN]],
        ])
    })

    it('orders the lines like the brands table and keeps the color of a brand when the ranks change', () => {
        const [own, rival, metrics] = EXAMPLE_PROMPT_SET_RANKINGS.brands
        const chartFor = (brands: AEOPromptSetRankingsApi['brands']): [string, number][] =>
            rankingsChart({ ...EXAMPLE_PROMPT_SET_RANKINGS, brands }).series.map((series) => [
                series.domain,
                series.colorIndex,
            ])

        expect(chartFor([own, rival, metrics])).toEqual([
            ['example.com', 0],
            ['rival.example.org', 2],
            ['metrics.example.net', 1],
        ])
        expect(chartFor([metrics, own, rival])).toEqual([
            ['metrics.example.net', 1],
            ['example.com', 0],
            ['rival.example.org', 2],
        ])
    })
})
