import type { AEOPromptDailyEngineStatsApi } from '../generated/api.schemas'
import { answerOutcomeChart, engineVisibilityChart } from './visibilityChart'

const DAILY: AEOPromptDailyEngineStatsApi[] = [
    { date: '2026-10-01', engine: 'openai-web-search', checks: 4, cited: 1, mentioned: 2, failed: 0, avg_position: 3 },
    {
        date: '2026-10-01',
        engine: 'claude-web-search',
        checks: 5,
        cited: 2,
        mentioned: 3,
        failed: 1,
        avg_position: 1.5,
    },
    {
        date: '2026-10-03',
        engine: 'claude-web-search',
        checks: 2,
        cited: 0,
        mentioned: 0,
        failed: 2,
        avg_position: null,
    },
]

describe('visibility charts', () => {
    it.each([
        ['cited', [0.5, NaN, NaN], [0.25, NaN, NaN]],
        ['mentioned', [0.75, NaN, NaN], [0.5, NaN, NaN]],
        ['position', [1.5, NaN, NaN], [3, NaN, NaN]],
    ] as const)(
        'plots %s per engine, leaving failed checks out and breaking the line on days without answers',
        (metric, claude, openai) => {
            const chart = engineVisibilityChart(DAILY, ['2026-10-01', '2026-10-02', '2026-10-03'], metric)

            expect(chart.series.map(({ engine, label, data }) => [engine, label, data])).toEqual([
                ['claude-web-search', 'Claude', claude],
                ['openai-web-search', 'ChatGPT', openai],
            ])
        }
    )

    it.each([
        ['cited', [3, 0, 0], [5, 0, 0]],
        ['mentioned', [5, 0, 0], [3, 0, 0]],
    ] as const)('counts %s answers per day across engines, leaving failed checks out', (metric, yes, no) => {
        const chart = answerOutcomeChart(DAILY, ['2026-10-01', '2026-10-02', '2026-10-03'], metric)

        expect([chart.yes, chart.no]).toEqual([yes, no])
    })
})
