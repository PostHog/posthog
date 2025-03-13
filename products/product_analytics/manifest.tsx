import { combineUrl } from 'kea-router'
import { AlertType } from 'lib/components/Alerts/types'

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
}
