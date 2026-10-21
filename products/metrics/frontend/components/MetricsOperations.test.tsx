import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { OtelMetricTypeEnumApi } from 'products/metrics/frontend/generated/api.schemas'

import { MetricsOperations } from './MetricsOperations'
import { MetricAggregation } from './metricsViewerLogic'

describe('MetricsOperations', () => {
    beforeEach(() => initKeaTests())

    afterEach(() => cleanup())

    const optionsInAggregationMenu = (
        aggregation: MetricAggregation,
        selectedMetricType: OtelMetricTypeEnumApi | null
    ): string[] => {
        const { container } = render(
            <MetricsOperations
                clause={{ rangeFunction: null, aggregation, selectedMetricType }}
                onRangeFunctionChange={() => {}}
                onAggregationChange={() => {}}
                disabledReason={null}
            />
        )
        fireEvent.click(container.querySelector('[data-attr="metrics-operation-aggregation"]')!)
        return Array.from(document.querySelectorAll('[data-attr^="metrics-operation-option-"]')).map((option) =>
            option.getAttribute('data-attr')!.replace('metrics-operation-option-', '')
        )
    }

    // A PromQL histogram percentile converted to the builder has no metric type until the picker loads.
    it.each<[string, MetricAggregation, OtelMetricTypeEnumApi | null, boolean]>([
        ['a histogram metric', 'histogram_p95', OtelMetricTypeEnumApi.Histogram, true],
        ['a converted histogram percentile without a metric type', 'histogram_p95', null, true],
        ['a gauge', 'sum', OtelMetricTypeEnumApi.Gauge, false],
    ])('offers histogram percentiles for %s: %s', (_name, aggregation, selectedMetricType, offered) => {
        const options = optionsInAggregationMenu(aggregation, selectedMetricType)
        expect(options.includes('histogram_p99')).toBe(offered)
        expect(options).toContain('sum')
    })
})
