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
        ['cited', [0.5], [0.25]],
        ['mentioned', [0.75], [0.5]],
        ['position', [1.5], [3]],
    ] as const)(
        'plots %s per engine on the days with answers, leaving failed checks and empty days out',
        (metric, claude, openai) => {
            // 2026-10-02 has no checks and 2026-10-03 only failed ones, so neither is on the axis.
            const chart = engineVisibilityChart(DAILY, ['2026-10-01', '2026-10-02', '2026-10-03'], metric)

            expect(chart.labels).toEqual(['2026-10-01'])
            expect(chart.series.map(({ engine, label, data }) => [engine, label, data])).toEqual([
                ['claude-web-search', 'Claude', claude],
                ['openai-web-search', 'ChatGPT', openai],
            ])
        }
    )

    it('keeps only the days with data in a long range, and leaves a day one engine missed empty rather than at 0', () => {
        const dates = Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`)
        const day = (date: string, engine: string): AEOPromptDailyEngineStatsApi => ({
            date,
            engine,
            checks: 4,
            cited: 1,
            mentioned: 2,
            failed: 0,
            avg_position: 2,
        })

        const chart = engineVisibilityChart(
            [
                day('2026-10-05', 'claude-web-search'),
                day('2026-10-20', 'claude-web-search'),
                day('2026-10-20', 'openai-web-search'),
            ],
            dates,
            'mentioned'
        )

        expect(chart.labels).toEqual(['2026-10-05', '2026-10-20'])
        expect(chart.series.map(({ engine, data }) => [engine, data])).toEqual([
            ['claude-web-search', [0.5, 0.5]],
            ['openai-web-search', [NaN, 0.5]],
        ])
    })

    it.each([
        ['cited', [3], [5]],
        ['mentioned', [5], [3]],
    ] as const)('counts %s answers per day with answers, leaving failed checks out', (metric, yes, no) => {
        const chart = answerOutcomeChart(DAILY, ['2026-10-01', '2026-10-02', '2026-10-03'], metric)

        expect(chart.labels).toEqual(['2026-10-01'])
        expect([chart.yes, chart.no]).toEqual([yes, no])
    })
})
