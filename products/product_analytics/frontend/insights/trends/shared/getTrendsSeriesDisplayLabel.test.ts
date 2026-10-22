import { FLAG_EVALUATIONS_TABLE } from 'scenes/feature-flags/flagEvaluationsTable'

import { AnyEntityNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getTrendsSeriesDisplayLabel, type TrendsSeriesLabelDeps } from './getTrendsSeriesDisplayLabel'

const seriesQuery = (node: AnyEntityNode): TrendsQuery => ({ kind: NodeKind.TrendsQuery, series: [node] })

const signups = seriesQuery({
    kind: NodeKind.EventsNode,
    event: '$pageview',
    name: '$pageview',
    custom_name: 'Signups',
})

const formulaQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
    trendsFilter: { formula: 'A + B' },
}

const NO_BREAKDOWN_DEPS: Omit<TrendsSeriesLabelDeps, 'querySource'> = {
    breakdownFilter: null,
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
}

const BREAKDOWN_DEPS: TrendsSeriesLabelDeps = {
    querySource: signups,
    breakdownFilter: { breakdown_type: 'event', breakdown: '$browser' },
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
}

const makeResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
    ({ id: 0, label: '$pageview', data: [], order: 0, ...overrides }) as IndexedTrendResult

describe('getTrendsSeriesDisplayLabel', () => {
    it.each([
        ['custom name wins over the event name', signups, {}, 'Signups'],
        [
            'humanizes the event name when no custom name',
            seriesQuery({ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }),
            {},
            'Pageview',
        ],
        [
            'uses the event name when not a built-in event',
            seriesQuery({ kind: NodeKind.EventsNode, event: 'purchase', name: 'purchase' }),
            {},
            'purchase',
        ],
        [
            'shows a flag calls series as the event',
            seriesQuery({
                kind: NodeKind.DataWarehouseNode,
                id: FLAG_EVALUATIONS_TABLE,
                table_name: FLAG_EVALUATIONS_TABLE,
                name: FLAG_EVALUATIONS_TABLE,
                id_field: 'uuid',
                timestamp_field: 'timestamp',
                distinct_id_field: 'distinct_id',
            }),
            { label: FLAG_EVALUATIONS_TABLE },
            'Feature flag called',
        ],
        ['falls back to the humanized label on a formula row', formulaQuery, { label: 'A + B' }, 'A + B'],
    ])('%s', (_name, querySource, overrides, expected) => {
        expect(
            getTrendsSeriesDisplayLabel(makeResult(overrides as Partial<IndexedTrendResult>), {
                ...NO_BREAKDOWN_DEPS,
                querySource,
            })
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
            { label: 'A + B' },
            { querySource: formulaQuery },
            'A + B · Chrome',
        ],
    ])('resolves to %s', (_name, resultOverrides, depOverrides, expected) => {
        const result = makeResult({
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
