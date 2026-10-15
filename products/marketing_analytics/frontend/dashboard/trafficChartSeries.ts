import { ActionsNode, EventsNode, NodeKind, WebAnalyticsConversionGoal } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

export const TRAFFIC_CHART_METRICS = [
    { value: 'visitors', label: 'Visitors' },
    { value: 'sessions', label: 'Sessions' },
    { value: 'pageviews', label: 'Page views' },
    { value: 'new_customers', label: 'New customers' },
] as const

export type TrafficChartMetric = (typeof TRAFFIC_CHART_METRICS)[number]['value']

const pageviewOrScreen: EventsNode = {
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
}

export function trafficChartSeries(
    metric: TrafficChartMetric,
    customerGoal: WebAnalyticsConversionGoal | null
): EventsNode | ActionsNode {
    if (metric === 'sessions') {
        return { ...pageviewOrScreen, math: BaseMathType.UniqueSessions, custom_name: 'Sessions' }
    }
    if (metric === 'pageviews') {
        return { ...pageviewOrScreen, math: BaseMathType.TotalCount, custom_name: 'Page views' }
    }
    if (metric === 'new_customers' && customerGoal) {
        const shared = {
            properties: customerGoal.properties,
            math: BaseMathType.UniqueUsers,
            custom_name: 'New customers',
        }
        return 'actionId' in customerGoal
            ? { kind: NodeKind.ActionsNode, id: customerGoal.actionId, ...shared }
            : { kind: NodeKind.EventsNode, event: customerGoal.customEventName, ...shared }
    }
    return { ...pageviewOrScreen, math: BaseMathType.UniqueUsers, custom_name: 'Visitors' }
}
