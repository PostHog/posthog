import { combineUrl } from 'kea-router'

import { AlertType } from 'lib/components/Alerts/types'
import { INSIGHT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import {
    DashboardFilter,
    HogQLFilters,
    HogQLVariable,
    Node,
    NodeKind,
    TileFilters,
} from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'

import {
    DashboardType,
    FileSystemIconColor,
    InsightSceneSource,
    InsightShortId,
    InsightType,
    ProductManifest,
} from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Product Analytics',
    urls: {
        insights: (): string => '/insights',
        insightNew: ({
            type,
            dashboardId,
            query,
            sceneSource,
        }: {
            type?: InsightType
            dashboardId?: DashboardType['id'] | null
            query?: Node
            sceneSource?: InsightSceneSource
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
                ...(sceneSource ? { sceneSource } : {}),
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
            variablesOverride?: Record<string, HogQLVariable>,
            filtersOverride?: DashboardFilter,
            tileFiltersOverride?: TileFilters
        ): string => {
            const params = [
                { param: 'dashboard', value: dashboardId },
                { param: 'variables_override', value: variablesOverride },
                { param: 'filters_override', value: filtersOverride },
                { param: 'tile_filters_override', value: tileFiltersOverride },
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
            iconType: 'product_analytics',
            href: (ref: string) => urls.insightView(ref as InsightShortId),
            iconColor: ['var(--color-product-product-analytics-light)'],
            filterKey: 'insight',
        },
    },
    treeItemsNew: [
        {
            path: `Insight/Trends`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.TRENDS }),
            iconType: 'insight/trends',
            iconColor: ['var(--color-insight-trends-light)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.trends,
            sceneKeys: ['Insight'],
        },
        {
            path: `Insight/Funnel`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.FUNNELS }),
            iconType: 'insight/funnels',
            iconColor: ['var(--color-insight-funnel-light)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.funnel,
            sceneKeys: ['Insight'],
        },
        {
            path: `Insight/Retention`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.RETENTION }),
            iconType: 'insight/retention',
            iconColor: ['var(--color-insight-retention-light)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.retention,
            sceneKeys: ['Insight'],
        },
        {
            path: `Insight/User paths`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.PATHS }),
            iconType: 'insight/paths',
            iconColor: ['var(--color-insight-user-paths-light)', 'var(--color-user-paths-dark)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.paths,
            sceneKeys: ['Insight'],
        },
        {
            path: `Insight/Stickiness`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.STICKINESS }),
            iconType: 'insight/stickiness',
            iconColor: ['var(--color-insight-stickiness-light)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.stickiness,
            sceneKeys: ['Insight'],
        },
        {
            path: `Insight/Lifecycle`,
            type: 'insight',
            href: urls.insightNew({ type: InsightType.LIFECYCLE }),
            iconType: 'insight/lifecycle',
            iconColor: ['var(--color-insight-lifecycle-light)'] as FileSystemIconColor,
            visualOrder: INSIGHT_VISUAL_ORDER.lifecycle,
            sceneKeys: ['Insight'],
        },
    ],
    treeItemsProducts: [
        {
            path: 'Product analytics',
            category: 'Analytics',
            type: 'insight',
            href: urls.insights(),
            iconType: 'product_analytics',
            iconColor: ['var(--color-product-product-analytics-light)'] as FileSystemIconColor,
            sceneKey: 'SavedInsights',
            sceneKeys: ['SavedInsights', 'Insight'],
        },
    ],
}
