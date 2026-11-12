import type {
    ExperimentApi,
    ExperimentExposureResponseApi,
    ExperimentHealthApi,
    ExperimentMetricResultRowApi,
    ExperimentResultsRunApi,
    ExperimentRunningTimeTargetApi,
} from '@/api/experiments'

import {
    bylineOf,
    exposureModelOf,
    formatChance,
    formatDelta,
    formatPValue,
    healthItemsOf,
    metricCardOf,
    metricDefsOf,
    progressOf,
    rolloutOf,
    statsSettingsOf,
    statusCardOf,
} from './detailModel'

const HOUR = 60 * 60_000

function experiment(overrides: Record<string, unknown> = {}): ExperimentApi {
    return {
        id: 7,
        name: 'Checkout button copy',
        feature_flag_key: 'checkout-button-copy',
        start_date: '2026-11-01T00:00:00Z',
        end_date: null,
        created_at: '2026-10-30T00:00:00Z',
        status: 'running',
        stats_config: { method: 'bayesian' },
        feature_flag: {
            id: 31,
            key: 'checkout-button-copy',
            active: true,
            filters: {
                groups: [{ properties: [], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            },
        },
        metrics: [
            {
                kind: 'ExperimentMetric',
                metric_type: 'funnel',
                uuid: 'm-1',
                name: 'Tickets opened',
                goal: 'decrease',
                series: [],
            },
        ],
        metrics_secondary: [],
        saved_metrics: [],
        ...overrides,
    } as unknown as ExperimentApi
}

function latest(
    rows: ExperimentMetricResultRowApi[],
    overrides: Partial<ExperimentResultsRunApi> = {}
): ExperimentResultsRunApi {
    return {
        id: 'run-1',
        status: 'completed',
        total_metrics: rows.length,
        completed_metrics: rows.length,
        failed_metrics: 0,
        query_to: '2026-11-12T02:00:00Z',
        completed_at: '2026-11-12T02:04:00Z',
        results: rows,
        ...overrides,
    } as unknown as ExperimentResultsRunApi
}

function row(overrides: Partial<ExperimentMetricResultRowApi> = {}): ExperimentMetricResultRowApi {
    return {
        metric_uuid: 'm-1',
        status: 'completed',
        error_message: null,
        result: {
            baseline: { key: 'control', number_of_samples: 2000, sum: 40, sum_squares: 40 },
            variant_results: [
                {
                    key: 'test',
                    method: 'bayesian',
                    number_of_samples: 2000,
                    sum: 30,
                    sum_squares: 30,
                    chance_to_win: 0.04,
                    credible_interval: [-0.4, -0.1],
                    significant: true,
                },
            ],
        },
        ...overrides,
    } as unknown as ExperimentMetricResultRowApi
}

describe('detailModel', () => {
    describe('statsSettingsOf', () => {
        test.each([
            ['Bayesian default', { method: 'bayesian' }, 'bayes', 0.95, 0.05],
            ['Bayesian 90% level', { method: 'bayesian', bayesian: { ci_level: 0.9 } }, 'bayes', 0.9, 0.1],
            ['Frequentist alpha 0.1', { method: 'frequentist', frequentist: { alpha: 0.1 } }, 'freq', 0.9, 0.1],
            [
                'Frequentist out-of-range alpha falls back',
                { method: 'frequentist', frequentist: { alpha: 5 } },
                'freq',
                0.95,
                0.05,
            ],
        ])('%s', (_name, config, method, level, alpha) => {
            const settings = statsSettingsOf(experiment({ stats_config: config }))
            expect(settings.method).toBe(method)
            expect(settings.level).toBeCloseTo(level)
            expect(settings.alpha).toBeCloseTo(alpha)
        })
    })

    describe('metricCardOf', () => {
        const defs = metricDefsOf(experiment())
        const def = defs.primary[0]

        it('turns a decrease goal around: chance to win, the good side and the conversion counts', () => {
            if (!def) {
                throw new Error('missing metric')
            }
            const card = metricCardOf(def, latest([row()]), ['control', 'test'])
            expect(card.state).toBe('ready')
            expect(card.baseline).toMatchObject({ key: 'control', numerator: 40, samples: 2000 })
            const [test] = card.variants
            expect(test?.chanceToWin).toBeCloseTo(0.96)
            expect(test?.better).toBe(true)
            expect(test?.side).toBe('good')
            expect(test?.numerator).toBe(30)
            expect(card.scale).toBeCloseTo(0.4)
        })

        test.each([
            ['pending', row({ status: 'pending', result: null }), 'pending'],
            ['failed', row({ status: 'failed', result: null, error_message: 'boom' }), 'failed'],
            [
                'no interval yet',
                row({
                    result: {
                        baseline: { key: 'control', number_of_samples: 2, sum: 0, sum_squares: 0 },
                        variant_results: [{ key: 'test', number_of_samples: 1, sum: 0, sum_squares: 0 }],
                    },
                }),
                'not_enough',
            ],
        ])('%s', (_name, metricRow, state) => {
            if (!def) {
                throw new Error('missing metric')
            }
            expect(metricCardOf(def, latest([metricRow]), ['control', 'test']).state).toBe(state)
        })

        it('names an unnamed metric after its event, like the web', () => {
            const unnamed = metricDefsOf(
                experiment({
                    metrics: [
                        {
                            kind: 'ExperimentMetric',
                            metric_type: 'mean',
                            uuid: 'm-2',
                            source: { kind: 'EventsNode', event: '$pageview' },
                        },
                    ],
                })
            )
            expect(unnamed.primary[0]).toMatchObject({ name: '$pageview', kind: 'mean', goal: 'increase' })
        })
    })

    describe('exposureModelOf', () => {
        const response = (pValue: number, checks: unknown[] = []): ExperimentExposureResponseApi =>
            ({
                timeseries: ['control', 'test', '$multiple'].map((variant) => ({
                    variant,
                    days: [],
                    exposure_counts: [],
                })),
                total_exposures: { control: 1368, test: 1166, $multiple: 38 },
                sample_ratio_mismatch: { expected: { control: 1267, test: 1267 }, p_value: pValue },
                health_checks: checks,
            }) as unknown as ExperimentExposureResponseApi

        it('reads expected counts as a split and keeps people in several variants out of the shares', () => {
            const model = exposureModelOf(response(0.0001), ['control', 'test'])
            expect(model?.total).toBe(2572)
            expect(model?.multiple).toBe(38)
            expect(model?.rows.map((r) => Math.round(r.share * 100))).toEqual([54, 46])
            expect(model?.srm?.expected).toEqual([0.5, 0.5])
        })

        test.each([
            ['a passing test', response(0.2)],
            ['a test the server skipped', response(0.0001, [{ key: 'srm', status: 'not_applicable' }])],
        ])('shows no warning for %s', (_name, payload) => {
            expect(exposureModelOf(payload, ['control', 'test'])?.srm).toBeNull()
        })
    })

    test.each([
        ['running', 'running', 'Running 11 days · started Nov 1'],
        ['paused', 'paused', 'Paused · started Nov 1, 11 days ago'],
    ] as const)('byline while %s', (_name, status, timing) => {
        const now = new Date(2026, 10, 12, 12, 0)
        const settings = statsSettingsOf(experiment())
        const started = experiment({ start_date: new Date(2026, 10, 1, 9, 0).toISOString() })
        expect(bylineOf(started, status, settings, { now, viewerUuid: null, clock24: true }).timing).toBe(timing)
    })

    describe('statusCardOf', () => {
        const now = new Date(2026, 10, 12, 7, 4).getTime()
        const stored = (hoursAgo: number): ExperimentResultsRunApi =>
            latest([], { query_to: new Date(now - hoursAgo * HOUR).toISOString() })
        const base = {
            status: 'running' as const,
            latestFailed: false,
            phase: { kind: 'idle' as const },
            mine: false,
            now,
            clock24: true,
        }

        test.each([
            [5, 'fresh'],
            [6, 'aging'],
            [12, 'stale'],
        ])('results %i h old read %s', (hours, tone) => {
            expect(statusCardOf({ ...base, latest: stored(hours) })?.tone).toBe(tone)
        })

        it('counts down the server window', () => {
            const card = statusCardOf({ ...base, latest: stored(1), phase: { kind: 'window', retryAt: now + 252_000 } })
            expect(card?.text).toBe('Updated just now · refresh again in 4:12')
        })

        it('keeps the old results while a run is still working', () => {
            const card = statusCardOf({ ...base, latest: stored(5), phase: { kind: 'stuck' } })
            expect(card).toMatchObject({
                strong: 'Still working',
                sub: 'The results from 02:04 stay until it is done.',
            })
        })

        it('says when a refresh came from this phone', () => {
            expect(statusCardOf({ ...base, latest: stored(0), mine: true })?.text).toBe(
                'Results from 07:04 · just now · your refresh'
            )
        })
    })

    describe('progressOf', () => {
        const target = (current: number, recommended: number | null, perDay: number): ExperimentRunningTimeTargetApi =>
            ({
                minimum_detectable_effect: 5,
                recommended_sample_size: recommended,
                current_sample_size: current,
                outlook: {
                    days_since_launch: 4,
                    exposures_per_day: perDay,
                    detectable_effect_now: 8,
                    upcoming_checkpoints: [],
                    reachable_effect: 4,
                },
            }) as ExperimentRunningTimeTargetApi

        test.each([
            ['rounds the days to go up', target(1242, 2200, 311), 'to_go', 4],
            ['reached at the target', target(6800, 6000, 567), 'reached', 0],
            ['early without a recommended size', target(214, null, 0), 'early', null],
            [
                'early while the results cover too little time',
                { ...target(214, 3000, 0), outlook: null },
                'early',
                null,
            ],
        ])('%s', (_name, payload, state, days) => {
            expect(progressOf(payload, null)).toMatchObject({ state, daysToGo: days })
        })
    })

    it('lists health findings most severe first, without the split finding the exposures card shows', () => {
        const health = {
            findings: [
                {
                    code: 'multiple_variants_share',
                    severity: 'info',
                    title: 'People saw several variants',
                    detail: 'a',
                },
                { code: 'flag_off_while_running', severity: 'critical', title: 'Flag is off', detail: 'b' },
            ],
            checks: [],
        } as unknown as ExperimentHealthApi
        const exposures = {
            timeseries: [],
            total_exposures: {},
            health_findings: [{ code: 'srm', severity: 'warning', title: 'Uneven split', detail: 'c' }],
        } as ExperimentExposureResponseApi
        expect(healthItemsOf(health, exposures).map((item) => item.title)).toEqual([
            'Flag is off',
            'People saw several variants',
        ])
    })

    test.each([
        ['running', 'Rollout 100% · split 50 / 50'],
        ['paused', 'Flag off · split 50 / 50'],
        ['draft', 'Off until launch · split 50 / 50'],
        ['complete', 'Still splitting 50 / 50'],
    ] as const)('rollout line while %s', (status, line) => {
        expect(rolloutOf(experiment(), status).line).toBe(line)
    })

    test.each([
        [formatDelta(-0.062), '−6.2%'],
        [formatDelta(0.124), '+12.4%'],
        [formatChance(0.9995), '> 99.9%'],
        [formatChance(0.991), '99.1%'],
        [formatPValue(0.0004), '< 0.001'],
        [formatPValue(0.009), '0.0090'],
    ])('formats %s', (actual, expected) => {
        expect(actual).toBe(expected)
    })
})
