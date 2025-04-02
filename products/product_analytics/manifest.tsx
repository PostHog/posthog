import { IconGraph } from '@posthog/icons'
import { combineUrl } from 'kea-router'
import { AlertType } from 'lib/components/Alerts/types'
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
        }: { type?: InsightType; dashboardId?: DashboardType['id'] | null; query?: Node } = {}): string => {
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
            icon: <IconGraph />,
            href: (ref: string) => urls.insightView(ref as InsightShortId),
        },
    },
    treeItemsNew: [
        {
            path: `Insight - Trends`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.TRENDS }),
        },
        {
            path: `Insight - Funnels`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.FUNNELS }),
        },
        {
            path: `Insight - Retention`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.RETENTION }),
        },
        {
            path: `Insight - User paths`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.PATHS }),
        },
        {
            path: `Insight - Stickiness`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.STICKINESS }),
        },
        {
            path: `Insight - Lifecycle`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.LIFECYCLE }),
        },
    ],
}
