import {
    errorsLookWorse,
    leadingOutcome,
    parseErrorSplit,
    parseVariantSeries,
    seriesFromTimeseries,
    variantOutcomes,
} from './releaseLaneInsights'

describe('releaseLaneInsights', () => {
    test.each([
        {
            name: 'flags the feature when its error rate is clearly higher',
            rows: [
                ['true', 200, 20],
                ['false', 100, 3],
                [null, 50, 9],
            ],
            worse: 'With the feature',
        },
        {
            name: 'stays quiet when the rates are close',
            rows: [
                ['true', 200, 8],
                ['false', 100, 4],
            ],
            worse: null,
        },
        {
            name: 'stays quiet when too few users saw the flag off',
            rows: [
                ['true', 200, 30],
                ['false', 10, 0],
            ],
            worse: null,
        },
    ])('$name', ({ rows, worse }) => {
        const errors = parseErrorSplit(rows)

        expect(errors.map((item) => item.label)).not.toContain('null')
        expect(errorsLookWorse(errors)?.label ?? null).toBe(worse)
    })

    it('measures each variant against control and picks the most likely winner', () => {
        const outcomes = variantOutcomes(
            {
                baseline: { key: 'control', number_of_samples: 100, sum: 50, sum_squares: 0 },
                variant_results: [
                    {
                        key: 'test',
                        number_of_samples: 100,
                        sum: 60,
                        sum_squares: 0,
                        method: 'bayesian',
                        chance_to_win: 0.9,
                        significant: true,
                    },
                    {
                        key: 'other',
                        number_of_samples: 100,
                        sum: 40,
                        sum_squares: 0,
                        method: 'bayesian',
                        chance_to_win: 0.1,
                        significant: false,
                    },
                ],
            },
            'increase'
        )

        expect(outcomes).toEqual([
            { key: 'test', change: expect.closeTo(0.2), chanceToWin: 0.9, significant: true },
            { key: 'other', change: expect.closeTo(-0.2), chanceToWin: 0.1, significant: false },
        ])
        expect(leadingOutcome(outcomes)?.key).toBe('test')
    })

    it('turns stored results and daily rows into one point per variant and day, without unknown variants', () => {
        expect(
            seriesFromTimeseries({
                '2026-11-20': {
                    baseline: { key: 'control', number_of_samples: 10, sum: 2, sum_squares: 0 },
                    variant_results: [{ key: 'test', number_of_samples: 10, sum: 4, sum_squares: 0 }],
                },
                '2026-11-21': null,
            })
        ).toEqual([
            { day: '2026-11-20', variant: 'control', value: 0.2 },
            { day: '2026-11-20', variant: 'test', value: 0.4 },
        ])
        expect(
            parseVariantSeries([
                ['2026-11-20 00:00:00', 'control', 0.2],
                ['2026-11-20 00:00:00', null, 0.9],
            ])
        ).toEqual([{ day: '2026-11-20', variant: 'control', value: 0.2 }])
    })
})
