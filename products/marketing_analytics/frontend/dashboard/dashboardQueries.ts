import { EventsNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyMathType } from '~/types'

export const TRAFFIC_BREAKDOWNS = {
    $channel_type: 'Channel',
    $entry_utm_source: 'UTM source',
    $entry_referring_domain: 'Referring domain',
    $entry_utm_campaign: 'Campaign',
    $entry_utm_medium: 'Medium',
    $entry_pathname: 'Landing page',
} as const

export type TrafficBreakdown = keyof typeof TRAFFIC_BREAKDOWNS
export type DashboardSection = 'acquisition' | 'engagement' | 'retention' | 'conversion' | 'revenue'

export function trafficQuery(
    section: 'acquisition' | 'engagement',
    breakdown: TrafficBreakdown,
    dateRange: TrendsQuery['dateRange'],
    compareFilter: TrendsQuery['compareFilter'],
    filterTestAccounts: boolean,
    chart: boolean = false
): InsightVizNode<TrendsQuery> {
    const base: EventsNode = { kind: NodeKind.EventsNode, event: '$pageview' }
    const series: EventsNode[] =
        section === 'acquisition'
            ? [
                  { ...base, math: BaseMathType.UniqueUsers, custom_name: 'Visitors' },
                  { ...base, math: BaseMathType.UniqueSessions, custom_name: 'Sessions' },
                  { ...base, math: BaseMathType.TotalCount, custom_name: 'Pageviews' },
              ]
            : [
                  {
                      ...base,
                      math: PropertyMathType.Average,
                      math_property: '$session_duration',
                      math_property_type: 'session_properties',
                      custom_name: 'Average session duration (seconds)',
                  },
                  {
                      ...base,
                      math: PropertyMathType.Average,
                      math_property: '$is_bounce',
                      math_property_type: 'session_properties',
                      custom_name: 'Bounce rate (0–1)',
                  },
              ]
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            dateRange,
            compareFilter,
            filterTestAccounts,
            interval: 'day',
            series: chart ? series.slice(0, 1) : series,
            breakdownFilter: chart ? undefined : { breakdown, breakdown_type: 'session', breakdown_limit: 25 },
            trendsFilter: { display: chart ? ChartDisplayType.ActionsLineGraph : ChartDisplayType.ActionsTable },
        },
        embedded: false,
        hidePersonsModal: true,
        showTable: false,
    }
}
