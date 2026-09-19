import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getTrendsSeriesDisplayLabel, type TrendsSeriesLabelDeps } from './getTrendsSeriesDisplayLabel'

const NO_BREAKDOWN_DEPS: TrendsSeriesLabelDeps = {
    breakdownFilter: null,
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
}

const BREAKDOWN_DEPS: TrendsSeriesLabelDeps = {
    breakdownFilter: { breakdown_type: 'event', breakdown: '$browser' },
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
}

const makeResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
    ({ id: 0, label: '$pageview', data: [], ...overrides }) as IndexedTrendResult

describe('getTrendsSeriesDisplayLabel', () => {
    it.each([
        ['custom name wins over the event name', { action: { name: '$pageview', custom_name: 'Signups' } }, 'Signups'],
        ['humanizes the event name when no custom name', { action: { name: '$pageview' } }, 'Pageview'],
        ['uses the action name when not a built-in event', { action: { name: 'purchase' } }, 'purchase'],
        [
            'falls back to the humanized label when there is no action (formula row)',
            { action: null, label: 'A + B' },
            'A + B',
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(
            getTrendsSeriesDisplayLabel(makeResult(overrides as Partial<IndexedTrendResult>), NO_BREAKDOWN_DEPS)
        ).toBe(expected)
    })

    it.each([
        ['the series name and breakdown value for multiple series', {}, {}, 'Signups · Chrome'],
        [
            'the series letter when display names collide',
            {},
            { seriesIdentification: 'letter-and-name' },
            'A Signups · Chrome',
        ],
        ['the breakdown value alone for a single-series query', {}, { isSingleSeriesDefinition: true }, 'Chrome'],
        [
            'the formula name and breakdown value for a formula row',
            { action: null, label: 'A + B' },
            {},
            'A + B · Chrome',
        ],
    ])('resolves to %s', (_name, resultOverrides, depOverrides, expected) => {
        const result = makeResult({
            action: { custom_name: 'Signups' } as IndexedTrendResult['action'],
            breakdown_value: 'Chrome',
            ...(resultOverrides as Partial<IndexedTrendResult>),
        })
        expect(
            getTrendsSeriesDisplayLabel(result, {
                ...BREAKDOWN_DEPS,
                ...(depOverrides as Partial<TrendsSeriesLabelDeps>),
            })
        ).toBe(expected)
    })
})
