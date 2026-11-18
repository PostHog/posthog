import type { AEOPromptSetRankingsApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_SET_RANKINGS } from './contentAutopilotStoryFixtures'
import { rankingsChart, visibilityChange } from './rankingsReport'

describe('rankingsReport', () => {
    it('aligns each brand to every day of the window and breaks the line on days without answers', () => {
        const rankings: AEOPromptSetRankingsApi = {
            ...EXAMPLE_PROMPT_SET_RANKINGS,
            window_from: '2026-10-01',
            window_to: '2026-10-03',
            brands: EXAMPLE_PROMPT_SET_RANKINGS.brands.slice(0, 2),
            daily: [
                { date: '2026-10-01', domain: 'example.com', answers: 4, visibility: 0.5 },
                { date: '2026-10-03', domain: 'example.com', answers: 4, visibility: 0.25 },
                { date: '2026-10-02', domain: 'rival.example.org', answers: 4, visibility: 0.75 },
            ],
        }

        const chart = rankingsChart(rankings)

        expect(chart.labels).toEqual(['2026-10-01', '2026-10-02', '2026-10-03'])
        expect(chart.series.map((series) => [series.domain, series.data])).toEqual([
            ['example.com', [0.5, NaN, 0.25]],
            ['rival.example.org', [NaN, 0.75, NaN]],
        ])
    })

    it.each([
        [0.41, 0.371, 3.9],
        [0.2, 0.25, -5],
        [0.4, null, null],
        [null, 0.4, null],
    ])('reports %s against %s as %s points', (visibility, previous, expected) => {
        expect(visibilityChange(visibility, previous)).toEqual(expected)
    })
})
