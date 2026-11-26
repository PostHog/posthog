import { type ExperimentExposureQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { healthDailyExposures, healthDailyShares, healthExposureDay } from './healthExposureDays'

const DAYS = ['2026-10-19', '2026-10-20', '2026-10-21']

const answer = (
    cumulative: Record<string, number[]>,
    expected?: Record<string, number>
): ExperimentExposureQueryResponse =>
    ({
        kind: NodeKind.ExperimentExposureQuery,
        timeseries: Object.entries(cumulative).map(([variant, counts]) => ({
            variant,
            days: DAYS,
            exposure_counts: counts,
        })),
        total_exposures: {},
        date_range: { date_from: '2026-10-19T00:00:00Z' },
        ...(expected ? { sample_ratio_mismatch: { expected, p_value: 0.0001 } } : {}),
    }) as ExperimentExposureQueryResponse

describe('healthExposureDays', () => {
    test.each([
        {
            name: 'counts each day from the cumulative answer, without users in several variants',
            exposures: answer({ control: [10, 30, 30], test: [10, 20, 25], $multiple: [1, 2, 3] }),
            expected: {
                days: DAYS,
                variants: [
                    { variant: 'control', counts: [10, 20, 0] },
                    { variant: 'test', counts: [10, 10, 5] },
                ],
            },
        },
        {
            name: 'keeps only the variants that the sample ratio test compares',
            exposures: answer(
                { control: [10, 20, 30], test: [5, 10, 15], holdout: [1, 2, 3] },
                { control: 1, test: 1 }
            ),
            expected: {
                days: DAYS,
                variants: [
                    { variant: 'control', counts: [10, 10, 10] },
                    { variant: 'test', counts: [5, 5, 5] },
                ],
            },
        },
        {
            name: 'has nothing to compare with one variant',
            exposures: answer({ control: [10, 20, 30] }),
            expected: null,
        },
    ])('healthDailyExposures: $name', ({ exposures, expected }) => {
        expect(healthDailyExposures(exposures)).toEqual(expected)
    })

    it('leaves a day with too few exposures out of the shares instead of drawing a jump', () => {
        const daily = healthDailyExposures(answer({ control: [30, 39, 59], test: [10, 11, 31] }))

        expect(daily && healthDailyShares(daily)).toEqual([
            { variant: 'control', shares: [75, NaN, 50] },
            { variant: 'test', shares: [25, NaN, 50] },
        ])
    })

    it("puts a change on the project's day, not the UTC day", () => {
        expect(healthExposureDay('2026-10-20T23:30:00Z', 'Europe/Berlin')).toEqual('2026-10-21')
    })
})
