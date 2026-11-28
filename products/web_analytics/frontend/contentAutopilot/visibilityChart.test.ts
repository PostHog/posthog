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

const DATES = Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`)

const day = (date: string, engine: string): AEOPromptDailyEngineStatsApi => ({
    date,
    engine,
    checks: 4,
    cited: 1,
    mentioned: 2,
    failed: 0,
    avg_position: 2,
})

describe('visibility charts', () => {
    it.each([
        ['cited', [0.5, NaN, NaN], [0.25, NaN, NaN]],
        ['mentioned', [0.75, NaN, NaN], [0.5, NaN, NaN]],
        ['position', [1.5, NaN, NaN], [3, NaN, NaN]],
    ] as const)(
        'plots %s per engine, leaving failed checks out and breaking the line on days without answers',
        (metric, claude, openai) => {
            const chart = engineVisibilityChart(DAILY, ['2026-10-01', '2026-10-02', '2026-10-03'], metric)

            expect(chart.labels).toEqual(['2026-10-01', '2026-10-02', '2026-10-03'])
            expect(chart.series.map(({ engine, label, data }) => [engine, label, data])).toEqual([
                ['claude-web-search', 'Claude', claude],
                ['openai-web-search', 'ChatGPT', openai],
            ])
        }
    )

    it.each([
        ['only the last day', ['2026-10-30'], ['2026-10-30'], [[0.5], [0.5]]],
        [
            'days 10 and 12, with day 11 a gap',
            ['2026-10-10', '2026-10-12'],
            DATES.slice(9),
            [
                [0.5, NaN, 0.5, ...Array(18).fill(NaN)],
                [0.5, NaN, 0.5, ...Array(18).fill(NaN)],
            ],
        ],
    ])('starts a 30-day axis at the first day of data when there is data on %s', (_name, withData, labels, data) => {
        const chart = engineVisibilityChart(
            withData.flatMap((date) => [day(date, 'claude-web-search'), day(date, 'openai-web-search')]),
            DATES,
            'mentioned'
        )

        expect(chart.labels).toEqual(labels)
        expect(chart.series.map((series) => series.data)).toEqual(data)
    })

    it('leaves a day one engine missed empty rather than at 0', () => {
        const chart = engineVisibilityChart(
            [
                day('2026-10-28', 'claude-web-search'),
                day('2026-10-29', 'claude-web-search'),
                day('2026-10-29', 'openai-web-search'),
            ],
            DATES,
            'mentioned'
        )

        expect(chart.series.map(({ engine, data }) => [engine, data])).toEqual([
            ['claude-web-search', [0.5, 0.5, NaN]],
            ['openai-web-search', [NaN, 0.5, NaN]],
        ])
    })

    it.each([
        ['cited', [3, 0, 0], [5, 0, 0]],
        ['mentioned', [5, 0, 0], [3, 0, 0]],
    ] as const)(
        'counts %s answers per day from the first day with answers, leaving failed checks out',
        (metric, yes, no) => {
            const chart = answerOutcomeChart(DAILY, ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-03'], metric)

            expect(chart.labels).toEqual(['2026-10-01', '2026-10-02', '2026-10-03'])
            expect([chart.yes, chart.no]).toEqual([yes, no])
        }
    )
})
