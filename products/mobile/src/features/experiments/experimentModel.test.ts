import type { ExperimentApi, ExperimentResultsRunApi, ExperimentVariantResultApi } from '@/api/experiments'

import {
    type ExperimentRow,
    experimentStatusOf,
    freshnessOf,
    headlineOf,
    primaryMetricsOf,
    primaryResultOf,
    secondaryMetricsOf,
    sortRunning,
    suggestedConclusion,
} from './experimentModel'

const NOW = Date.parse('2026-11-04T07:00:00Z')

function experiment(overrides: Record<string, unknown> = {}): ExperimentApi {
    return {
        id: 1,
        name: 'Checkout copy',
        feature_flag_key: 'checkout-copy',
        start_date: '2026-10-20T10:00:00Z',
        end_date: null,
        status: 'running',
        feature_flag: { active: true, filters: { multivariate: { variants: [{ key: 'control' }, { key: 'test' }] } } },
        metrics: [{ uuid: 'm1', name: 'Checkout', metric_type: 'funnel', goal: 'increase' }],
        saved_metrics: [],
        running_time_calculation: { recommended_sample_size: 5000 },
        ...overrides,
    } as unknown as ExperimentApi
}

function latest(variant: Partial<ExperimentVariantResultApi>, samples = 1000): ExperimentResultsRunApi {
    return {
        id: 'run-1',
        status: 'completed',
        query_to: '2026-11-04T02:00:00Z',
        completed_at: '2026-11-04T02:04:00Z',
        result_source: 'recalculation',
        results: [
            {
                metric_uuid: 'm1',
                status: 'completed',
                configuration_status: 'current',
                error_message: null,
                result: {
                    baseline: { key: 'control', number_of_samples: samples, sum: 100, sum_squares: 100 },
                    variant_results: [
                        { key: 'test', number_of_samples: samples, sum: 120, sum_squares: 120, ...variant },
                    ],
                },
            },
        ],
    } as unknown as ExperimentResultsRunApi
}

function row(id: string, overrides: Partial<ExperimentRow>): ExperimentRow {
    return {
        id,
        name: id,
        flagKey: id,
        status: 'running',
        method: 'bayes',
        variants: [],
        startedAt: '2026-10-01T00:00:00Z',
        endedAt: null,
        createdAt: '2026-09-30T00:00:00Z',
        days: 10,
        conclusion: null,
        shippedVariant: null,
        changed: false,
        headline: { kind: 'needs_data' },
        createdBy: null,
        isNew: false,
        targetSampleSize: null,
        ...overrides,
    }
}

describe('experimentStatusOf', () => {
    test.each<[string, Record<string, unknown>, string]>([
        ['a frozen experiment', { status: 'exposure_frozen' }, 'frozen'],
        ['an ended experiment', { status: 'stopped' }, 'complete'],
        ['an older payload with an inactive flag', { status: undefined, feature_flag: { active: false } }, 'paused'],
        ['an older payload without a launch', { status: undefined, start_date: null }, 'draft'],
    ])('reads %s', (_name, overrides, expected) => {
        expect(experimentStatusOf(experiment(overrides))).toBe(expected)
    })
})

describe('headlineOf', () => {
    test('reads a significant Bayesian winner with its change from the interval midpoint', () => {
        const headline = headlineOf(
            experiment(),
            latest({ method: 'bayesian', credible_interval: [0.04, 0.2], chance_to_win: 0.99, significant: true })
        )
        expect(headline).toMatchObject({ kind: 'significant', leader: 'test', better: true, exposures: 2000 })
        expect(headline !== 'none' && headline.delta).toBeCloseTo(0.12)
    })

    test('turns better and the chance to win around for a lower-is-better metric', () => {
        const decrease = experiment({ metrics: [{ uuid: 'm1', metric_type: 'funnel', goal: 'decrease' }] })
        const run = latest({
            method: 'bayesian',
            credible_interval: [0.02, 0.1],
            chance_to_win: 0.97,
            significant: true,
        })
        expect(headlineOf(decrease, run)).toMatchObject({ kind: 'significant', better: false })
        expect(primaryResultOf(decrease, run)?.variants[0]?.chanceToWin).toBeCloseTo(0.03)
        expect(suggestedConclusion(primaryResultOf(decrease, run))).toBe('lost')
    })

    test.each<[string, Partial<ExperimentVariantResultApi>, number, string]>([
        [
            'a likely Bayesian winner',
            { method: 'bayesian', credible_interval: [-0.02, 0.16], chance_to_win: 0.93 },
            1000,
            'leading',
        ],
        [
            'an unclear Bayesian result',
            { method: 'bayesian', credible_interval: [-0.13, 0.21], chance_to_win: 0.65 },
            1000,
            'needs_data',
        ],
        [
            'an unclear result past its sample target',
            { method: 'frequentist', confidence_interval: [-0.1, 0.12], p_value: 0.6 },
            3000,
            'target',
        ],
    ])('reads %s', (_name, variant, samples, kind) => {
        expect(headlineOf(experiment(), latest(variant, samples))).toMatchObject({ kind })
    })

    test('says no results yet when the stored results lack the primary metric', () => {
        expect(headlineOf(experiment(), null)).toEqual({ kind: 'not_yet', resultsAt: undefined })
        expect(headlineOf(experiment({ status: 'draft', start_date: null }), null)).toBe('none')
    })
})

test('sortRunning puts decisions first, then changed rows, then the newest launch', () => {
    const rows = [
        row('old', { startedAt: '2026-09-01T00:00:00Z' }),
        row('new', { startedAt: '2026-10-30T00:00:00Z' }),
        row('changed', { changed: true, startedAt: '2026-08-01T00:00:00Z' }),
        row('ship', { headline: { kind: 'significant', better: true }, startedAt: '2026-07-01T00:00:00Z' }),
        row('loading', { headline: 'loading', startedAt: '2026-10-31T00:00:00Z' }),
    ]
    expect(sortRunning(rows).map((item) => item.id)).toEqual(['ship', 'changed', 'loading', 'new', 'old'])
})

test('freshnessOf reads the data cutoff and the daily placeholder', () => {
    const run = { ...latest({}), result_source: 'timeseries_fallback' } as ExperimentResultsRunApi
    expect(freshnessOf(run, NOW)).toEqual({
        resultsAt: new Date('2026-11-04T02:00:00Z'),
        ageMs: 5 * 60 * 60_000,
        source: 'fallback',
    })
    expect(freshnessOf(null, NOW)).toEqual({ resultsAt: null, ageMs: null, source: null })
})

test('orders own and shared metrics together by the saved uuid list, as the web does', () => {
    const withShared = experiment({
        metrics: [
            { uuid: 'own-1', name: 'Own one', metric_type: 'funnel' },
            { uuid: 'own-2', name: 'Own two', metric_type: 'mean' },
        ],
        saved_metrics: [
            {
                name: 'Shared revenue',
                metadata: { type: 'primary' },
                effective_query: { uuid: 'shared-1', name: 'q', metric_type: 'mean' },
            },
            { name: 'Shared untyped', metadata: {}, effective_query: { uuid: 'shared-2', metric_type: 'mean' } },
            {
                name: 'Shared secondary',
                metadata: { type: 'secondary' },
                query: { uuid: 'shared-3', metric_type: 'funnel' },
            },
        ],
        primary_metrics_ordered_uuids: ['shared-1', 'missing', 'own-2'],
    })
    expect(primaryMetricsOf(withShared).map((metric) => metric.name)).toEqual(['Shared revenue', 'Own two', 'Own one'])
    expect(secondaryMetricsOf(withShared).map((metric) => metric.uuid)).toEqual(['shared-3'])
})
