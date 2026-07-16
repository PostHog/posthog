import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import type { TracingLatencyHeatmapData } from './durationBuckets'
import { heatmapBrushToFilters } from './heatmapBrush'

const MS = 1_000_000

const DATA: TracingLatencyHeatmapData = {
    timeBuckets: ['t0', 't1', 't2', 't3'],
    bucketsNs: [1 * MS, 2 * MS, 5 * MS, 10 * MS],
    labels: ['1ms', '2ms', '5ms', '10ms'],
    cells: [],
}

const EMPTY_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

describe('heatmapBrushToFilters', () => {
    it('maps columns to bucket-edge dates and rows to a ms duration chip pair', () => {
        const result = heatmapBrushToFilters(
            DATA,
            { x: { startIndex: 1, endIndex: 2 }, y: { startIndex: 1, endIndex: 2 } },
            EMPTY_GROUP,
            '2026-06-02T09:00:00Z'
        )
        // date_to is the START of the bucket after the last selected column.
        expect(result?.dateRange).toEqual({ date_from: 't1', date_to: 't3' })
        expect((result?.filterGroup?.values[0] as UniversalFiltersGroup).values).toEqual([
            // 2ms..5ms rows cover [2ms, 10ms) — the upper edge is the bucket after the last row.
            { type: PropertyFilterType.Span, key: 'duration', operator: PropertyOperator.GreaterThanOrEqual, value: 2 },
            { type: PropertyFilterType.Span, key: 'duration', operator: PropertyOperator.LessThan, value: 10 },
        ])
    })

    it('falls back to the current range end when the selection reaches the last column', () => {
        const result = heatmapBrushToFilters(
            DATA,
            { x: { startIndex: 2, endIndex: 3 }, y: { startIndex: 0, endIndex: 1 } },
            EMPTY_GROUP,
            '2026-06-02T09:00:00Z'
        )
        expect(result?.dateRange).toEqual({ date_from: 't2', date_to: '2026-06-02T09:00:00Z' })
    })

    it('treats a full-height selection as a time zoom with no duration filters', () => {
        const result = heatmapBrushToFilters(
            DATA,
            { x: { startIndex: 0, endIndex: 1 }, y: { startIndex: 0, endIndex: 3 } },
            EMPTY_GROUP,
            null
        )
        expect(result).toEqual({ dateRange: { date_from: 't0', date_to: 't2' } })
    })

    it('replaces a prior brush duration pair instead of stacking, keeping other filters', () => {
        const groupWithFilters: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Span,
                            key: 'name',
                            operator: PropertyOperator.Exact,
                            value: ['GET /api'],
                        },
                        {
                            type: PropertyFilterType.Span,
                            key: 'duration',
                            operator: PropertyOperator.GreaterThanOrEqual,
                            value: 1,
                        },
                        {
                            type: PropertyFilterType.Span,
                            key: 'duration',
                            operator: PropertyOperator.LessThan,
                            value: 2,
                        },
                    ],
                },
            ],
        }
        const result = heatmapBrushToFilters(
            DATA,
            { x: { startIndex: 0, endIndex: 0 }, y: { startIndex: 2, endIndex: 2 } },
            groupWithFilters,
            null
        )
        expect((result?.filterGroup?.values[0] as UniversalFiltersGroup).values).toEqual([
            { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: ['GET /api'] },
            { type: PropertyFilterType.Span, key: 'duration', operator: PropertyOperator.GreaterThanOrEqual, value: 5 },
            { type: PropertyFilterType.Span, key: 'duration', operator: PropertyOperator.LessThan, value: 10 },
        ])
    })

    it('returns null when the selection resolves to no start bucket', () => {
        expect(
            heatmapBrushToFilters(
                { timeBuckets: [], bucketsNs: [], labels: [], cells: [] },
                { x: { startIndex: 0, endIndex: 0 }, y: { startIndex: 0, endIndex: 0 } },
                EMPTY_GROUP,
                null
            )
        ).toBeNull()
    })
})
