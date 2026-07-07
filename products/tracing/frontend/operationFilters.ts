import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    SpanPropertyFilter,
} from '~/types'

export interface DurationRange {
    minNs: number
    maxNs: number
}

const NS_PER_MS = 1_000_000

/**
 * Filter group scoping a spans query to one operation, optionally to a duration range.
 * The span `duration` property filter's value unit is milliseconds — the backend translates
 * it to `duration_nano` (see translate_span_filter in backend/logic.py).
 */
export function operationFilterGroup(spanName: string, durationRange: DurationRange | null): PropertyGroupFilter {
    const values: SpanPropertyFilter[] = [
        { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: [spanName] },
    ]
    if (durationRange) {
        values.push({
            type: PropertyFilterType.Span,
            key: 'duration',
            operator: PropertyOperator.GreaterThanOrEqual,
            value: durationRange.minNs / NS_PER_MS,
        })
        values.push({
            type: PropertyFilterType.Span,
            key: 'duration',
            operator: PropertyOperator.LessThan,
            value: durationRange.maxNs / NS_PER_MS,
        })
    }
    return {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values }],
    }
}
