import {
    type ExperimentMetric,
    ExperimentMetricType,
    ExperimentWarehouseNativeMathType,
    type ExperimentWarehouseNativeNode,
    NodeKind,
} from '~/queries/schema/schema-general'

import {
    type WarehouseNativeBinding,
    alignMetricsWithExposure,
    experimentUsesWarehouseNativeSources,
    getExperimentMetricDataSources,
    getExposureSourceBlockedReasons,
    getWarehouseNativeMetricError,
    getWarehouseNativeMismatchError,
    toWarehouseNativeMetric,
} from './warehouseNativeSources'

const BINDING: WarehouseNativeBinding = {
    connection_id: 'connection-1',
    unit: { unit_type: 'customer', id_namespace: 'billing_customer_id' },
}

const warehouseSource = (overrides: Partial<ExperimentWarehouseNativeNode> = {}): ExperimentWarehouseNativeNode => ({
    kind: NodeKind.ExperimentWarehouseNativeNode,
    ...BINDING,
    query: 'SELECT customer_id AS entity_id, paid_at AS timestamp, amount FROM billing.payments',
    math: ExperimentWarehouseNativeMathType.TotalCount,
    ...overrides,
})

const meanMetric = (source: ExperimentWarehouseNativeNode): ExperimentMetric => ({
    kind: NodeKind.ExperimentMetric,
    uuid: 'metric-1',
    metric_type: ExperimentMetricType.MEAN,
    source,
})

const EVENTS_METRIC: ExperimentMetric = {
    kind: NodeKind.ExperimentMetric,
    uuid: 'metric-2',
    metric_type: ExperimentMetricType.MEAN,
    source: { kind: NodeKind.EventsNode, event: '$pageview' },
}

describe('warehouseNativeSources', () => {
    it('turns a funnel metric into a warehouse-native mean metric that keeps its identity', () => {
        const funnel: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            uuid: 'metric-3',
            name: 'Revenue',
            metric_type: ExperimentMetricType.FUNNEL,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }

        expect(toWarehouseNativeMetric(funnel, BINDING)).toEqual({
            kind: NodeKind.ExperimentMetric,
            uuid: 'metric-3',
            name: 'Revenue',
            goal: undefined,
            metric_type: ExperimentMetricType.MEAN,
            source: warehouseSource({ query: '' }),
        })
    })

    it('keeps the SQL of a ratio source and replaces an event source, so the ratio never mixes sources', () => {
        const numerator = warehouseSource({ connection_id: 'old-connection', math_property: 'amount' })
        const ratio: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.RATIO,
            numerator,
            denominator: { kind: NodeKind.EventsNode, event: '$pageview' },
        }

        expect(toWarehouseNativeMetric(ratio, BINDING)).toMatchObject({
            numerator: { ...numerator, connection_id: 'connection-1' },
            denominator: warehouseSource({ query: '' }),
        })
    })

    it('moves a metric to the connection and unit of a changed exposure, and leaves the other metrics alone', () => {
        const aligned = meanMetric(warehouseSource())
        const stale = meanMetric(warehouseSource({ connection_id: 'old-connection' }))

        const result = alignMetricsWithExposure([aligned, stale, EVENTS_METRIC], BINDING)

        expect(result[0]).toBe(aligned)
        expect(result[1]).toEqual(aligned)
        expect(result[2]).toBe(EVENTS_METRIC)
    })

    it.each([
        ['no connection', warehouseSource({ connection_id: '' }), 'Select a BigQuery connection'],
        [
            'no unit',
            warehouseSource({ unit: { unit_type: ' ', id_namespace: 'billing_customer_id' } }),
            'Enter the randomization unit',
        ],
        ['no query', warehouseSource({ query: '  ' }), 'Enter a SQL query for every source'],
        [
            'a sum without a column',
            warehouseSource({ math: ExperimentWarehouseNativeMathType.Sum }),
            'Enter the column to sum',
        ],
        [
            'a complete sum',
            warehouseSource({ math: ExperimentWarehouseNativeMathType.Sum, math_property: 'amount' }),
            null,
        ],
    ])('reports why a metric with %s cannot be saved', (_, source, expected) => {
        expect(getWarehouseNativeMetricError(meanMetric(source))).toBe(expected)
    })

    it.each([
        [
            'a warehouse-native exposure and no metrics',
            {
                exposure_criteria: {
                    exposure_config: {
                        ...warehouseSource(),
                        kind: NodeKind.ExperimentWarehouseNativeExposureConfig as const,
                    },
                },
            },
            true,
            { warehouseNative: false, posthog: false },
        ],
        [
            'a warehouse-native shared metric',
            { saved_metrics: [{ query: meanMetric(warehouseSource()) }] },
            true,
            { warehouseNative: true, posthog: false },
        ],
        ['event metrics only', { metrics: [EVENTS_METRIC] }, false, { warehouseNative: false, posthog: true }],
    ])('knows which data sources an experiment with %s reads', (_, experiment, usesWarehouse, metricDataSources) => {
        const full = { metrics: [], metrics_secondary: [], saved_metrics: [], ...experiment }

        expect(experimentUsesWarehouseNativeSources(full)).toBe(usesWarehouse)
        expect(getExperimentMetricDataSources(full)).toEqual(metricDataSources)
    })

    it.each([
        ['an event exposure with event metrics', false, { warehouseNative: false, posthog: true }, 'warehouseNative'],
        ['a warehouse-native exposure with its metrics', true, { warehouseNative: true, posthog: false }, 'posthog'],
        ['an exposure with no metrics', true, { warehouseNative: false, posthog: false }, null],
    ] as const)('blocks the other data source for %s', (_, exposureIsWarehouseNative, metricDataSources, blocked) => {
        const reasons = getExposureSourceBlockedReasons(exposureIsWarehouseNative, metricDataSources)

        expect(!!reasons.warehouseNative).toBe(blocked === 'warehouseNative')
        expect(!!reasons.posthog).toBe(blocked === 'posthog')
    })

    it.each([
        ['a shared metric on the same connection and unit', warehouseSource(), null],
        ['a shared metric on another connection', warehouseSource({ connection_id: 'connection-2' }), /shared metric/],
        [
            'a shared metric on another unit',
            warehouseSource({ unit: { unit_type: 'account', id_namespace: 'crm_account_id' } }),
            /shared metric/,
        ],
    ])('checks a warehouse-native exposure against %s', (_, sharedSource, expected) => {
        const exposure = { ...warehouseSource(), kind: NodeKind.ExperimentWarehouseNativeExposureConfig as const }

        const error = getWarehouseNativeMismatchError(exposure, { warehouseNative: true, posthog: false }, [
            meanMetric(sharedSource),
        ])

        if (expected) {
            expect(error).toMatch(expected)
        } else {
            expect(error).toBeNull()
        }
    })
})
