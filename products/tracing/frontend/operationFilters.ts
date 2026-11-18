import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    SpanPropertyFilter,
} from '~/types'

import type { DurationRange } from './durationBuckets'

export type { DurationRange } from './durationBuckets'

const NS_PER_MS = 1_000_000

/**
 * The route attribute that narrows a bare-method span name ("GET") to one endpoint ("GET /users/:id").
 * Application observability labels those endpoints by method and route, and links here with both.
 */
export interface OperationRoute {
    attribute: string
    value: string
}

/**
 * The route attributes in the order application observability reads them: a span labelled by a later
 * attribute must not set an earlier one, even to an empty value, or it belongs to the earlier attribute's endpoint.
 * Mirrors ROUTE_ATTRIBUTES in products/apm/backend/logic/health/sources.py.
 */
const ROUTE_ATTRIBUTES = ['http.route', 'url.template']

/**
 * Filter group scoping a spans query to one operation, optionally to a duration range.
 * The span `duration` property filter's value unit is milliseconds — the backend translates
 * it to `duration_nano` (see translate_span_filter in backend/logic.py).
 */
export function operationFilterGroup(
    spanName: string,
    durationRange: DurationRange | null,
    route: OperationRoute | null = null
): PropertyGroupFilter {
    const values: SpanPropertyFilter[] = [
        { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: [spanName] },
    ]
    if (route) {
        values.push({
            type: PropertyFilterType.SpanAttribute,
            key: route.attribute,
            operator: PropertyOperator.Exact,
            value: [route.value],
        })
        const precedence = ROUTE_ATTRIBUTES.indexOf(route.attribute)
        for (const earlier of precedence > 0 ? ROUTE_ATTRIBUTES.slice(0, precedence) : []) {
            values.push({ type: PropertyFilterType.SpanAttribute, key: earlier, operator: PropertyOperator.IsNotSet })
        }
    }
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
