import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { insightsApi } from 'scenes/insights/utils/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import type { MetricsQuery, MetricsQueryClause } from '~/queries/schema/schema-general'
import type { DashboardType } from '~/types'

import { metricsAttributeValuesRetrieve, metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'
import type { _MetricNameApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricsStarterDashboardLogicType } from './metricsStarterDashboardLogicType'
import { RECOMMENDED_AGGREGATION_BY_TYPE, toKnownMetricType } from './metricsViewerLogic'

// One dashboard, one insight per picked metric, each charted with the
// aggregation its type recommends and scoped to the picked service — the
// onboarding doc's starter set, productized.
export const metricsStarterDashboardLogic = kea<metricsStarterDashboardLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsStarterDashboardLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        openModal: true,
        closeModal: true,
        setDashboardName: (dashboardName: string) => ({ dashboardName }),
        setServiceName: (serviceName: string) => ({ serviceName }),
        setSelectedMetrics: (selectedMetrics: string[]) => ({ selectedMetrics }),
        createDashboard: true,
        createDashboardSuccess: (createdDashboard: DashboardType) => ({ createdDashboard }),
        createDashboardFailure: (message: string) => ({ message }),
    }),
    reducers({
        isModalOpen: [false, { openModal: () => true, closeModal: () => false }],
        // The whole form resets on close so a reopen can't silently mint a near-duplicate.
        dashboardName: [
            '' as string,
            { setDashboardName: (_, { dashboardName }) => dashboardName, closeModal: () => '' },
        ],
        // '' = all services: the insights get no service filter.
        serviceName: ['' as string, { setServiceName: (_, { serviceName }) => serviceName, closeModal: () => '' }],
        selectedMetrics: [
            [] as string[],
            { setSelectedMetrics: (_, { selectedMetrics }) => selectedMetrics, closeModal: () => [] },
        ],
        // Drives the create button's loading/disabled state so a double click can't
        // fire twice; the listener's cache flag is the authoritative in-flight guard.
        creating: [
            false,
            {
                createDashboard: () => true,
                createDashboardSuccess: () => false,
                createDashboardFailure: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        services: [
            [] as string[],
            {
                loadServices: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await metricsAttributeValuesRetrieve(String(values.currentTeamId), {
                        key: 'service.name',
                    })
                    breakpoint()
                    return response.results.map((value) => value.name)
                },
            },
        ],
        metricOptions: [
            [] as _MetricNameApi[],
            {
                loadMetricOptions: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await metricsValuesRetrieve(String(values.currentTeamId), {})
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        openModal: () => {
            actions.loadServices({})
            actions.loadMetricOptions({})
        },
        createDashboard: async () => {
            // kea-loaders doesn't dedupe concurrent runs, so the create is a plain
            // listener with an explicit in-flight guard.
            if (cache.creatingDashboard) {
                return
            }
            cache.creatingDashboard = true
            // Snapshot the form before the first await: a modal dismissed or edited
            // mid-create must not change (or empty) what gets created.
            const name = values.dashboardName.trim()
            const selectedMetrics = [...values.selectedMetrics]
            const serviceName = values.serviceName
            const typeByName: Record<string, string> = Object.fromEntries(
                values.metricOptions.map((option) => [option.name, option.metric_type])
            )
            let dashboard: DashboardType | null = null
            let created = 0
            try {
                if (!name || !selectedMetrics.length) {
                    actions.createDashboardFailure('Pick a dashboard name and at least one metric')
                    return
                }
                dashboard = await api.create<DashboardType>(`api/environments/${values.currentTeamId}/dashboards/`, {
                    name,
                })
                for (const metricName of selectedMetrics) {
                    const rawType = typeByName[metricName]
                    // The names endpoint reports raw ingest strings; only enum members
                    // may reach the API — mirrors the viewer's metricsQueryNode.
                    const metricType = toKnownMetricType(rawType)
                    const recommended = (rawType && RECOMMENDED_AGGREGATION_BY_TYPE[rawType]) || 'avg'
                    const clause: MetricsQueryClause = {
                        name: 'a',
                        metricName,
                        // The REST viewer's 'p95' shorthand maps to the node's quantile aggregation.
                        aggregation: recommended === 'p95' ? 'quantile' : recommended,
                        ...(recommended === 'p95' ? { quantile: 0.95 } : {}),
                        ...(metricType ? { metricType } : {}),
                        ...(serviceName
                            ? { filters: [{ key: 'service.name', op: 'eq' as const, value: serviceName }] }
                            : {}),
                    }
                    const query: MetricsQuery = { kind: NodeKind.MetricsQuery, clauses: [clause] }
                    await insightsApi.create({
                        name: `${metricName} (${recommended})`,
                        saved: true,
                        dashboards: [dashboard.id],
                        query,
                    })
                    created++
                }
                actions.createDashboardSuccess(dashboard)
            } catch (error: any) {
                if (dashboard) {
                    // The dashboard exists with a partial insight set — say so and take
                    // the user there rather than implying nothing happened (a retry
                    // from the modal would mint a duplicate dashboard).
                    lemonToast.warning(
                        `Dashboard "${dashboard.name}" created, but only ${created} of ${selectedMetrics.length} insights could be added`
                    )
                    actions.createDashboardSuccess(dashboard)
                } else {
                    actions.createDashboardFailure(error?.detail || error?.message || 'Failed to create the dashboard')
                }
            } finally {
                cache.creatingDashboard = false
            }
        },
        createDashboardSuccess: ({ createdDashboard }) => {
            actions.closeModal()
            lemonToast.success(`Dashboard "${createdDashboard.name}" created`)
            router.actions.push(urls.dashboard(createdDashboard.id))
        },
        createDashboardFailure: ({ message }) => {
            lemonToast.error(message)
        },
    })),
])
