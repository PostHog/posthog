import { type ExperimentExposureQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { healthChangeDays, healthDailyExposures, healthDailyShares } from './healthExposureDays'

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

    test.each([
        {
            name: 'leaves a day with too few exposures out of the shares instead of drawing a jump',
            cumulative: { control: [30, 39, 59], test: [10, 11, 31] },
            expected: [
                { variant: 'control', shares: [75, NaN, 50] },
                { variant: 'test', shares: [25, NaN, 50] },
            ],
        },
        {
            name: 'has no line to draw when only one day has enough exposures',
            cumulative: { control: [30, 39, 49], test: [10, 11, 21] },
            expected: null,
        },
    ])('healthDailyShares: $name', ({ cumulative, expected }) => {
        const daily = healthDailyExposures(answer(cumulative))

        expect(daily && healthDailyShares(daily)).toEqual(expected)
    })

    it("puts a change on the project's day, not the UTC day, and only on a day of the answer", () => {
        expect(
            healthChangeDays(
                ['2026-10-20T23:30:00Z', '2026-10-21T08:00:00Z', '2026-10-25T08:00:00Z'],
                'Europe/Berlin',
                DAYS
            )
        ).toEqual(['2026-10-21'])
    })
})
