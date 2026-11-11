import { type BreakdownFilter, type EventsNode, NodeKind, type TrendsQuery } from '~/queries/schema/schema-general'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { type AggregatedDisplayLabelDeps, getAggregatedDisplayLabel } from './getAggregatedDisplayLabel'

const mkResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
    ({
        id: 0,
        label: '',
        count: 0,
        data: [],
        days: [],
        labels: [],
        aggregated_value: 0,
        ...overrides,
    }) as IndexedTrendResult

const jobCreated: EventsNode = { kind: NodeKind.EventsNode, event: 'Job Created', name: 'Job Created' }
const querySource = (node: EventsNode): TrendsQuery => ({ kind: NodeKind.TrendsQuery, series: [node] })

const deps = (overrides?: Partial<AggregatedDisplayLabelDeps>): AggregatedDisplayLabelDeps => ({
    querySource: querySource(jobCreated),
    stackBreakdowns: false,
    breakdownFilter: null,
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
    ...overrides,
})

describe('getAggregatedDisplayLabel', () => {
    it('prefers the series custom name over the event name when there is no breakdown', () => {
        const r = mkResult({ label: 'Job Created', order: 0 })
        expect(
            getAggregatedDisplayLabel(r, deps({ querySource: querySource({ ...jobCreated, custom_name: 'Articles' }) }))
        ).toBe('Articles')
    })

    it('falls back to the event name when no custom name is set', () => {
        const r = mkResult({ label: 'Job Created', order: 0 })
        expect(getAggregatedDisplayLabel(r, deps())).toBe('Job Created')
    })

    it('uses the breakdown value, not the custom name, when a breakdown is present', () => {
        const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }
        const r = mkResult({ label: 'Chrome', breakdown_value: 'Chrome', order: 0 })
        expect(
            getAggregatedDisplayLabel(
                r,
                deps({ breakdownFilter, querySource: querySource({ ...jobCreated, custom_name: 'Job Created' }) })
            )
        ).toBe('Chrome')
    })

    it('uses the entity name for the band in stacked-breakdown mode', () => {
        const r = mkResult({ label: 'Chrome', breakdown_value: 'Chrome', order: 0 })
        expect(
            getAggregatedDisplayLabel(
                r,
                deps({ stackBreakdowns: true, querySource: querySource({ ...jobCreated, custom_name: 'Articles' }) })
            )
        ).toBe('Articles')
    })
})
