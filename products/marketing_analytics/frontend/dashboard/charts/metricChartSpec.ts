import { ConversionGoalFilter, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

export interface MetricChartSpec {
    label: string
    series: EventsNode[]
    formula?: string
    format: 'number' | 'percentage' | 'duration' | 'decimal'
}

/** Visitors and sessions count across pageviews and screenviews alike, which is what web analytics
 * treats as traffic. */
const trafficEvent = (math: BaseMathType): EventsNode => ({
    kind: NodeKind.EventsNode,
    event: null,
    properties: [
        {
            key: 'event',
            type: PropertyFilterType.EventMetadata,
            operator: PropertyOperator.Exact,
            value: ['$pageview', '$screen'],
        },
    ],
    math,
})

const sessionProperty = (property: string): EventsNode => ({
    kind: NodeKind.EventsNode,
    event: '$pageview',
    math: PropertyMathType.Average,
    math_property: property,
    math_property_type: 'session_properties',
})

const pageviews = (math: BaseMathType): EventsNode => ({
    kind: NodeKind.EventsNode,
    event: '$pageview',
    math,
})

/** Warehouse goals key on distinct id, so the events-based series cannot express them. */
const goalSeries = (
    goal: ConversionGoalFilter,
    math: BaseMathType | PropertyMathType,
    property?: string
): EventsNode | null => {
    const base =
        goal.kind === NodeKind.ActionsNode
            ? { kind: NodeKind.ActionsNode, id: goal.id }
            : goal.kind === NodeKind.EventsNode
              ? { kind: NodeKind.EventsNode, event: goal.event }
              : null
    if (!base) {
        return null
    }
    return {
        ...base,
        math,
        ...(property ? { math_property: property } : {}),
        properties: goal.properties,
    } as EventsNode
}

const withSeries = (spec: Omit<MetricChartSpec, 'series'>, series: (EventsNode | null)[]): MetricChartSpec | null =>
    series.every((entry): entry is EventsNode => entry !== null) ? { ...spec, series } : null

/** Everything a card can chart. A metric absent from here has no trend the query engine can
 * express, so its card does not open one. */
export function metricChartSpec(key: string, goal: ConversionGoalFilter | null): MetricChartSpec | null {
    switch (key) {
        case 'visitors':
            return { label: 'Visitors', series: [trafficEvent(BaseMathType.UniqueUsers)], format: 'number' }
        case 'sessions':
            return { label: 'Sessions', series: [trafficEvent(BaseMathType.UniqueSessions)], format: 'number' }
        case 'views':
            return { label: 'Pageviews', series: [pageviews(BaseMathType.TotalCount)], format: 'number' }
        case 'acquired':
            return {
                label: 'New visitors',
                series: [trafficEvent(BaseMathType.FirstTimeForUser)],
                format: 'number',
            }
        case 'newVisitorShare':
            return {
                label: 'New visitor share',
                series: [trafficEvent(BaseMathType.FirstTimeForUser), trafficEvent(BaseMathType.UniqueUsers)],
                formula: 'A / B * 100',
                format: 'percentage',
            }
        case 'session duration':
            return {
                label: 'Avg. session duration',
                series: [sessionProperty('$session_duration')],
                format: 'duration',
            }
        case 'bounce rate':
            return {
                label: 'Bounce rate',
                series: [sessionProperty('$is_bounce')],
                formula: 'A * 100',
                format: 'percentage',
            }
        case 'pages_per_session':
            return {
                label: 'Pages per session',
                series: [pageviews(BaseMathType.TotalCount), trafficEvent(BaseMathType.UniqueSessions)],
                formula: 'A / B',
                format: 'decimal',
            }
        case 'pages_per_visitor':
            return {
                label: 'Pageviews per visitor',
                series: [pageviews(BaseMathType.TotalCount), trafficEvent(BaseMathType.UniqueUsers)],
                formula: 'A / B',
                format: 'decimal',
            }
        case 'sessions_per_visitor':
            return {
                label: 'Sessions per visitor',
                series: [trafficEvent(BaseMathType.UniqueSessions), trafficEvent(BaseMathType.UniqueUsers)],
                formula: 'A / B',
                format: 'decimal',
            }
        case 'total conversions':
            return goal
                ? withSeries({ label: 'Conversions', format: 'number' }, [goalSeries(goal, BaseMathType.TotalCount)])
                : null
        case 'conversion rate':
            return goal
                ? withSeries({ label: 'Conversion rate', formula: 'A / B * 100', format: 'percentage' }, [
                      goalSeries(goal, BaseMathType.UniqueUsers),
                      trafficEvent(BaseMathType.UniqueUsers),
                  ])
                : null
        case 'conversion_value':
            return goal?.math_property
                ? withSeries({ label: 'Conversion value', format: 'number' }, [
                      goalSeries(goal, PropertyMathType.Sum, goal.math_property),
                  ])
                : null
        case 'avg_conversion_value':
            return goal?.math_property
                ? withSeries({ label: 'Avg. conversion value', format: 'number' }, [
                      goalSeries(goal, PropertyMathType.Average, goal.math_property),
                  ])
                : null
        default:
            // Retention's return rates and days-to-return are cohort measures, not a series the
            // trends engine can plot over the same date range.
            return null
    }
}
