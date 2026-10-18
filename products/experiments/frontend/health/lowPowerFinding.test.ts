import type { MetricWithResult } from 'scenes/experiments/utils'

import {
    type CachedNewExperimentQueryResponse,
    type ExperimentMetric,
    ExperimentMetricType,
} from '~/queries/schema/schema-general'

import { lowPowerFinding } from './lowPowerFinding'

const metricWithResult = (metricType: ExperimentMetricType, sums: number[]): MetricWithResult => {
    const [baseline, ...variants] = sums.map((sum, index) => ({
        key: index === 0 ? 'control' : `test-${index}`,
        number_of_samples: 10000,
        sum,
        sum_squares: sum,
    }))
    return {
        metric: { metric_type: metricType } as ExperimentMetric,
        result: { baseline, variant_results: variants } as unknown as CachedNewExperimentQueryResponse,
        error: null,
        displayIndex: 0,
        metricIndex: 0,
    }
}

const funnel = (...sums: number[]): MetricWithResult => metricWithResult(ExperimentMetricType.FUNNEL, sums)
const mean = (...sums: number[]): MetricWithResult => metricWithResult(ExperimentMetricType.MEAN, sums)

const lowPower = (subcode: string, evidence: Record<string, number>): unknown =>
    expect.objectContaining({ code: 'low_power', severity: 'info', subcode, evidence })

describe('lowPowerFinding', () => {
    test.each([
        {
            name: 'a funnel variant with few conversions',
            primaryMetrics: [funnel(5000, 140)],
            expected: lowPower('few_conversions', { fewest_conversions_per_variant: 140 }),
        },
        {
            name: 'the fewest conversions across funnel metrics',
            primaryMetrics: [funnel(5000, 4000), funnel(900, 120)],
            expected: lowPower('few_conversions', { fewest_conversions_per_variant: 120 }),
        },
        {
            name: 'a mean metric with small sums, which are not conversions',
            primaryMetrics: [mean(10, 20)],
            expected: null,
        },
        {
            name: 'a funnel with enough conversions in every variant',
            primaryMetrics: [funnel(5000, 400)],
            expected: null,
        },
        {
            name: 'few conversions when the sample reached the recommended size',
            primaryMetrics: [funnel(150, 140)],
            recommendedSampleSize: 20000,
            expected: null,
        },
        {
            name: 'exposures far below the recommended sample size',
            primaryMetrics: [mean(10, 20)],
            recommendedSampleSize: 50000,
            expected: lowPower('below_recommended_sample_size', {
                total_exposures: 20000,
                recommended_sample_size: 50000,
            }),
        },
        {
            name: 'exposures over half of the recommended sample size',
            primaryMetrics: [mean(10, 20)],
            recommendedSampleSize: 30000,
            expected: null,
        },
        {
            name: 'results that the page does not show yet',
            primaryMetrics: [funnel(5, 3)],
            totalExposures: 49,
            expected: null,
        },
        {
            name: 'a draft',
            primaryMetrics: [funnel(5000, 140)],
            isExperimentDraft: true,
            expected: null,
        },
    ])('$name', ({ primaryMetrics, totalExposures = 20000, recommendedSampleSize, isExperimentDraft, expected }) => {
        const finding = lowPowerFinding({
            primaryMetrics,
            totalExposures,
            recommendedSampleSize,
            isExperimentDraft: isExperimentDraft ?? false,
        })
        expect(finding).toEqual(expected)
    })
})
