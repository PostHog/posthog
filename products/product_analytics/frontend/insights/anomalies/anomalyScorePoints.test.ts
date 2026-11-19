import { CompareLabelType } from '~/types'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'
import type { AnomalyBucketApi, AnomalyInsightSeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { buildAnomalyScorePoints, contiguousRuns, scoreHistoryRange } from './anomalyScorePoints'

function makeResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        id: 0,
        seriesIndex: 0,
        colorIndex: 0,
        order: 0,
        label: 'checkout_completed',
        count: 6,
        aggregated_value: 6,
        data: [1, 2, 3],
        labels: [],
        days: ['2026-11-14', '2026-11-15', '2026-11-16'],
        ...overrides,
    } as IndexedTrendResult
}

function makeBucket(bucket_start: string, flag: boolean | null): AnomalyBucketApi {
    return {
        bucket_start,
        scored: flag !== null,
        value: 1,
        score: flag ? 0.99 : 0.1,
        flag,
        scored_at: null,
        details: null,
    }
}

function makeScored(overrides: Partial<AnomalyInsightSeriesApi> = {}): AnomalyInsightSeriesApi {
    return {
        series_key: 'key',
        series_label: 'checkout_completed',
        breakdown_value: null,
        buckets: [],
        ...overrides,
    } as AnomalyInsightSeriesApi
}

describe('anomalyScorePoints', () => {
    it('buildAnomalyScorePoints marks only the flagged buckets that the chart shows', () => {
        const scored = makeScored({
            buckets: [
                makeBucket('2026-11-13T00:00:00+00:00', true),
                makeBucket('2026-11-15T00:00:00+00:00', true),
                makeBucket('2026-11-16T00:00:00+00:00', false),
            ],
        })

        expect(buildAnomalyScorePoints([scored], [makeResult()])).toEqual([
            { index: 1, date: '2026-11-15', score: 0.99, seriesIndex: 0 },
        ])
    })

    it('matches an hourly bucket in a project timezone to the chart hour', () => {
        const result = makeResult({ days: ['2026-11-16 03:00:00', '2026-11-16 04:00:00'], data: [1, 2] })
        const scored = makeScored({ buckets: [makeBucket('2026-11-16T04:00:00-08:00', true)] })

        expect(buildAnomalyScorePoints([scored], [result])).toEqual([
            { index: 1, date: '2026-11-16 04:00:00', score: 0.99, seriesIndex: 0 },
        ])
    })

    it.each([
        ['a breakdown value', 'pro', 'pro', 1],
        ['a list breakdown', ['pro', 'eu'], 'pro::eu', 1],
        ['another breakdown value', 'free', 'pro', null],
    ])('matches a scored series to the chart series with %s', (_name, chartBreakdown, scoredBreakdown, expected) => {
        const results = [
            makeResult({ seriesIndex: 0, breakdown_value: 'other' }),
            makeResult({ seriesIndex: 1, breakdown_value: chartBreakdown }),
            makeResult({ seriesIndex: 2, breakdown_value: chartBreakdown, compare_label: CompareLabelType.Previous }),
        ]
        const scored = makeScored({
            breakdown_value: scoredBreakdown,
            buckets: [makeBucket('2026-11-15T00:00:00+00:00', true)],
        })

        expect(buildAnomalyScorePoints([scored], results).map((point) => point.seriesIndex)).toEqual(
            expected === null ? [] : [expected]
        )
    })

    it('joins neighbouring flagged buckets into one run', () => {
        expect(contiguousRuns([7, 3, 4, 4, 9, 5])).toEqual([
            [3, 5],
            [7, 7],
            [9, 9],
        ])
    })

    it.each([
        ['a short chart as it is', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z'],
        ['a chart longer than a year from its newest year', '2024-07-01T00:00:00Z', '2025-11-17T00:00:00.000Z'],
    ])('asks for the score history of %s', (_name, dateFrom, expectedFrom) => {
        expect(scoreHistoryRange(dateFrom, '2026-11-17T00:00:00Z')).toEqual({
            date_from: expectedFrom,
            date_to: '2026-11-17T00:00:00Z',
        })
    })
})
