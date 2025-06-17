import { IconGraph } from '@posthog/icons'
import { combineUrl } from 'kea-router'
import { AlertType } from 'lib/components/Alerts/types'
import { INSIGHT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { HogQLFilters, HogQLVariable, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'

import { DashboardType, InsightShortId, InsightType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Product Analytics',
    urls: {
        insights: (): string => '/insights',
        insightNew: ({
            type,
            dashboardId,
            query,
        }: {
            type?: InsightType
            dashboardId?: DashboardType['id'] | null
            query?: Node
        } = {}): string => {
            // Redirect HogQL queries to SQL editor
            if (isHogQLQuery(query)) {
                return urls.sqlEditor(query.query)
            }

            // Redirect DataNode and DataViz queries with HogQL source to SQL editor
            if ((isDataVisualizationNode(query) || isDataTableNode(query)) && isHogQLQuery(query.source)) {
                return urls.sqlEditor(query.source.query)
            }

            return combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, {
                ...(type ? { insight: type } : {}),
                ...(query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}),
            }).url
        },
        insightNewHogQL: ({ query, filters }: { query: string; filters?: HogQLFilters }): string =>
            urls.insightNew({
                query: {
                    kind: NodeKind.DataTableNode,
                    source: { kind: 'HogQLQuery', query, filters },
                } as any,
            }),
        insightEdit: (id: InsightShortId): string => `/insights/${id}/edit`,
        insightView: (
            id: InsightShortId,
            dashboardId?: number,
            variablesOverride?: Record<string, HogQLVariable>
        ): string => {
            const params = [
                { param: 'dashboard', value: dashboardId },
                { param: 'variables_override', value: variablesOverride },
            ]
                .filter((n) => Boolean(n.value))
                .map((n) => `${n.param}=${encodeURIComponent(JSON.stringify(n.value))}`)
                .join('&')
            return `/insights/${id}${params.length ? `?${params}` : ''}`
        },
        insightSubcriptions: (id: InsightShortId): string => `/insights/${id}/subscriptions`,
        insightSubcription: (id: InsightShortId, subscriptionId: string): string =>
            `/insights/${id}/subscriptions/${subscriptionId}`,
        insightSharing: (id: InsightShortId): string => `/insights/${id}/sharing`,
        savedInsights: (tab?: string): string => `/insights${tab ? `?tab=${tab}` : ''}`,
        insightAlerts: (insightShortId: InsightShortId): string => `/insights/${insightShortId}/alerts`,
        insightAlert: (insightShortId: InsightShortId, alertId: AlertType['id']): string =>
            `/insights/${insightShortId}/alerts?alert_id=${alertId}`,
        alert: (alertId: string): string => `/insights?tab=alerts&alert_id=${alertId}`,
        alerts: (): string => `/insights?tab=alerts`,
    },
    fileSystemTypes: {
        insight: {
            name: 'Insight',
            icon: <IconGraph />,
            href: (ref: string) => urls.insightView(ref as InsightShortId),
            iconColor: ['var(--product-product-analytics-light)'],
            filterKey: 'insight',
        },
    },
    treeItemsNew: [
        {
            path: `Insight/Trends`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.TRENDS }),
            iconType: 'insightTrends',
            visualOrder: INSIGHT_VISUAL_ORDER.trends,
        },
        {
            path: `Insight/Funnel`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.FUNNELS }),
            iconType: 'insightFunnel',
            visualOrder: INSIGHT_VISUAL_ORDER.funnel,
        },
        {
            path: `Insight/Retention`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.RETENTION }),
            iconType: 'insightRetention',
            visualOrder: INSIGHT_VISUAL_ORDER.retention,
        },
        {
            path: `Insight/User paths`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.PATHS }),
            iconType: 'insightUserPaths',
            visualOrder: INSIGHT_VISUAL_ORDER.paths,
        },
        {
            path: `Insight/Stickiness`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.STICKINESS }),
            iconType: 'insightStickiness',
            visualOrder: INSIGHT_VISUAL_ORDER.stickiness,
        },
        {
            path: `Insight/Lifecycle`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.LIFECYCLE }),
            iconType: 'insightLifecycle',
            visualOrder: INSIGHT_VISUAL_ORDER.lifecycle,
        },
        {
            path: `Insight/Calendar heatmap`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.CALENDAR_HEATMAP }),
            iconType: 'insightCalendarHeatmap',
            visualOrder: INSIGHT_VISUAL_ORDER.calendarHeatmap,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Product analytics',
            category: 'Analytics',
            type: 'insight',
            href: urls.insights(),
        },
    ],
}
