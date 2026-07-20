// Pure mapping from a heatmap 2D brush onto the tracing filters. Kept out of the kea logic so
// the geometry → filter translation is unit-testable without the logic's import graph.

import { DateRange } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    SpanPropertyFilter,
    UniversalFiltersGroup,
} from '~/types'

import { selectionToDurationRange, type TracingLatencyHeatmapData } from './durationBuckets'
import type { DurationRange } from './operationFilters'

const NS_PER_MS = 1_000_000

export interface HeatmapBrushSelection {
    /** Inclusive column range into the heatmap's time buckets. */
    x: { startIndex: number; endIndex: number }
    /** Inclusive row range into the heatmap's duration buckets (0 = bottom/smallest). */
    y: { startIndex: number; endIndex: number }
}

function isBrushDurationFilter(filter: unknown): boolean {
    const f = filter as Partial<SpanPropertyFilter> | null
    return (
        f?.type === PropertyFilterType.Span &&
        f?.key === 'duration' &&
        (f?.operator === PropertyOperator.GreaterThanOrEqual || f?.operator === PropertyOperator.LessThan)
    )
}

/** The current filter group with the brushed duration range applied as a >=min / <max pair of
 *  `duration` span filters (ms — the unit the chips and the backend translation use). Any prior
 *  >=/< duration pair is replaced, so successive brushes refine instead of stacking. */
function withDurationFilters(group: UniversalFiltersGroup, range: DurationRange): UniversalFiltersGroup {
    const inner = group.values[0] as UniversalFiltersGroup | undefined
    const keptValues = (inner?.values ?? []).filter((filter) => !isBrushDurationFilter(filter))
    const durationFilters: SpanPropertyFilter[] = [
        {
            type: PropertyFilterType.Span,
            key: 'duration',
            operator: PropertyOperator.GreaterThanOrEqual,
            value: range.minNs / NS_PER_MS,
        },
        {
            type: PropertyFilterType.Span,
            key: 'duration',
            operator: PropertyOperator.LessThan,
            value: range.maxNs / NS_PER_MS,
        },
    ]
    return {
        ...group,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...keptValues, ...durationFilters],
            } as UniversalFiltersGroup,
            ...group.values.slice(1),
        ],
    }
}

/**
 * Filter updates for a completed heatmap brush, or null when the selection resolves to nothing.
 *
 * x maps to a date range using the same bucket-edge convention as the sparkline's time selection:
 * `date_to` is the START of the bucket after the last selected column (buckets are anchored at
 * their start), falling back to the current range's end on the final column. y maps to a
 * `duration` chip pair via the 1-2-5 bucket edges — unless the brush spans every row, which reads
 * as a plain time-range zoom and leaves the filters untouched.
 *
 * Returned as one object so the caller can dispatch a single `setFilters` (one re-query), with
 * the chips appearing in the filter bar as ordinary removable filters.
 */
export function heatmapBrushToFilters(
    data: TracingLatencyHeatmapData,
    selection: HeatmapBrushSelection,
    currentFilterGroup: UniversalFiltersGroup,
    currentDateTo: string | null | undefined
): { dateRange: DateRange; filterGroup?: UniversalFiltersGroup } | null {
    const dateFrom = data.timeBuckets[selection.x.startIndex]
    if (!dateFrom) {
        return null
    }
    const dateRange: DateRange = {
        date_from: dateFrom,
        date_to: data.timeBuckets[selection.x.endIndex + 1] ?? currentDateTo ?? null,
    }

    const spansAllRows = selection.y.startIndex <= 0 && selection.y.endIndex >= data.bucketsNs.length - 1
    if (spansAllRows) {
        return { dateRange }
    }

    const durationRange = selectionToDurationRange(data.bucketsNs, selection.y.startIndex, selection.y.endIndex)
    if (!durationRange) {
        return { dateRange }
    }

    return { dateRange, filterGroup: withDurationFilters(currentFilterGroup, durationRange) }
}
