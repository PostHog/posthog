import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import {
    LegacyExperimentMetricResult,
    legacyExpectedRunningTime,
    legacyGetVariantCalculationResult,
    legacyMinimumSampleSizePerVariant,
    legacyRecommendedExposureForCountData,
} from './legacyExperimentCalculations'

describe('experimentCalculations', () => {
    describe('minimumSampleSizePerVariant', () => {
        it('given an mde, calculates correct sample size', () => {
            // Using the rule of thumb: sampleSize = 16 * sigma^2 / (mde^2)
            expect(legacyMinimumSampleSizePerVariant(30, 20)).toEqual(29)

            expect(legacyMinimumSampleSizePerVariant(30, 40)).toEqual(43)

            expect(legacyMinimumSampleSizePerVariant(30, 0)).toEqual(0)
        })
    })

    describe('expectedRunningTime', () => {
        it('given sample size and entrants, calculates correct running time', () => {
            // 500 entrants over 14 days, 1000 sample size, so need twice the time
            expect(legacyExpectedRunningTime(500, 1000)).toEqual(28)

            // 500 entrants over 14 days, 250 sample size, so need half the time
            expect(legacyExpectedRunningTime(500, 250)).toEqual(7)

            // 0 entrants over 14 days, so infinite running time
            expect(legacyExpectedRunningTime(0, 1000)).toEqual(Infinity)

            // Custom duration
            expect(legacyExpectedRunningTime(500, 1000, 7)).toEqual(14)
        })
    })

    describe('getVariantCalculationResult', () => {
        it('reports no results for a response in the new ExperimentQuery format', () => {
            // A legacy experiment holding a new-format metric gets this shape back: the same `kind`,
            // but no `metric` and none of the per-variant fields the legacy calculations read.
            const result = {
                kind: NodeKind.ExperimentQuery,
                metric: null,
                baseline: { key: 'control', number_of_samples: 100, sum: 10, sum_squares: 10 },
                variant_results: [{ key: 'test', number_of_samples: 100, sum: 20, sum_squares: 20 }],
            } as unknown as LegacyExperimentMetricResult

            expect(legacyGetVariantCalculationResult(result, 'test', InsightType.FUNNELS)).toEqual({
                conversionRate: null,
                count: null,
                exposure: null,
                mean: null,
                credibleInterval: null,
                delta: null,
            })
        })
    })

    describe('recommendedExposureForCountData', () => {
        it('given control count data, calculates correct exposure time', () => {
            // Using formula: 4 / (sqrt(lambda1/days) - sqrt(lambda2/days))^2

            // 1000 count over 14 days
            expect(legacyRecommendedExposureForCountData(30, 1000)).toEqual(2.8)

            // 10,000 count over 14 days - 10x count, so 1/10th running time
            expect(legacyRecommendedExposureForCountData(30, 10000)).toEqual(0.3)

            // 0 count, so should be Infinity (can't calculate with zero)
            expect(legacyRecommendedExposureForCountData(30, 0)).toEqual(Infinity)
        })
    })
})
