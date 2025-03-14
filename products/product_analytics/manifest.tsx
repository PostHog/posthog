import { IconGraph } from '@posthog/icons'
import { combineUrl } from 'kea-router'
import { AlertType } from 'lib/components/Alerts/types'
import { urls } from 'scenes/urls'

import { HogQLFilters, HogQLVariable } from '~/queries/schema/schema-general'

import { DashboardType, InsightShortId, InsightType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Product Analytics',
    urls: {
        insights: (): string => '/insights',
        insightNew: ({
            type,
            dashboardId,
            query,
        }: { type?: InsightType; dashboardId?: DashboardType['id'] | null; query?: Node } = {}): string =>
            combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, {
                ...(type ? { insight: type } : {}),
                ...(query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}),
            }).url,
        insightNewHogQL: ({ query, filters }: { query: string; filters?: HogQLFilters }): string =>
            combineUrl(
                `/data-warehouse`,
                {},
                {
                    q: JSON.stringify({
                        kind: 'DataTableNode',
                        full: true,
                        source: { kind: 'HogQLQuery', query, filters },
                    }),
                }
            ).url,
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
    treeItems: [
        {
            path: `Create new/Insight/Trends`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.TRENDS }),
        },
        {
            path: `Create new/Insight/Funnels`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.FUNNELS }),
        },
        {
            path: `Create new/Insight/Retention`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.RETENTION }),
        },
        {
            path: `Create new/Insight/User paths`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.PATHS }),
        },
        {
            path: `Create new/Insight/Stickiness`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.STICKINESS }),
        },
        {
            path: `Create new/Insight/Lifecycle`,
            type: 'insight',
            href: () => urls.insightNew({ type: InsightType.LIFECYCLE }),
        },
    ],
}
