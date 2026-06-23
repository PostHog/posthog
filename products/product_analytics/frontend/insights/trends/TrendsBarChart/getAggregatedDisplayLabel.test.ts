import type { IndexedTrendResult } from 'scenes/trends/types'

import type { BreakdownFilter } from '~/queries/schema/schema-general'

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

const deps = (overrides?: Partial<AggregatedDisplayLabelDeps>): AggregatedDisplayLabelDeps => ({
    stackBreakdowns: false,
    breakdownFilter: null,
    cohorts: undefined,
    formatPropertyValueForDisplay: undefined,
    ...overrides,
})

describe('getAggregatedDisplayLabel', () => {
    it('prefers the series custom name over the event name when there is no breakdown', () => {
        const r = mkResult({
            label: 'Job Created',
            action: { id: '0', type: 'events', name: 'Job Created', custom_name: 'Articles' },
        })
        expect(getAggregatedDisplayLabel(r, deps())).toBe('Articles')
    })

    it('falls back to the event name when no custom name is set', () => {
        const r = mkResult({ label: 'Job Created', action: { id: '0', type: 'events', name: 'Job Created' } })
        expect(getAggregatedDisplayLabel(r, deps())).toBe('Job Created')
    })

    it('uses the breakdown value, not the custom name, when a breakdown is present', () => {
        const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }
        const r = mkResult({
            label: 'Chrome',
            breakdown_value: 'Chrome',
            action: { id: '0', type: 'events', name: 'Job Created', custom_name: 'Job Created' },
        })
        expect(getAggregatedDisplayLabel(r, deps({ breakdownFilter }))).toBe('Chrome')
    })

    it('uses the entity name for the band in stacked-breakdown mode', () => {
        const r = mkResult({
            label: 'Chrome',
            breakdown_value: 'Chrome',
            action: { id: '0', type: 'events', name: 'Job Created', custom_name: 'Articles' },
        })
        expect(getAggregatedDisplayLabel(r, deps({ stackBreakdowns: true }))).toBe('Articles')
    })
})
