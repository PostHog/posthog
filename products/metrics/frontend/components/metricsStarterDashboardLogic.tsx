import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { insightsApi } from 'scenes/insights/utils/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { DashboardType } from '~/types'

import { metricsAttributeValuesRetrieve, metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'
import type { _MetricNameApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricsStarterDashboardLogicType } from './metricsStarterDashboardLogicType'
import { RECOMMENDED_AGGREGATION_BY_TYPE } from './metricsViewerLogic'

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
        dashboardName: ['' as string, { setDashboardName: (_, { dashboardName }) => dashboardName }],
        // '' = all services: the insights get no service filter.
        serviceName: ['' as string, { setServiceName: (_, { serviceName }) => serviceName }],
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
                    return response.results
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
            try {
                const name = values.dashboardName.trim()
                if (!name || !values.selectedMetrics.length) {
                    actions.createDashboardFailure('Pick a dashboard name and at least one metric')
                    return
                }
                const typeByName = Object.fromEntries(
                    values.metricOptions.map((option) => [option.name, option.metric_type])
                )
                const dashboard = await api.create<DashboardType>(
                    `api/environments/${values.currentTeamId}/dashboards/`,
                    { name }
                )
                for (const metricName of values.selectedMetrics) {
                    const metricType = typeByName[metricName]
                    const aggregation = (metricType && RECOMMENDED_AGGREGATION_BY_TYPE[metricType]) || 'avg'
                    await insightsApi.create({
                        name: `${metricName} (${aggregation})`,
                        saved: true,
                        dashboards: [dashboard.id],
                        query: {
                            kind: 'MetricsQuery',
                            clauses: [
                                {
                                    name: 'a',
                                    metricName,
                                    aggregation,
                                    ...(metricType ? { metricType } : {}),
                                    ...(values.serviceName
                                        ? {
                                              filters: [{ key: 'service.name', op: 'eq', value: values.serviceName }],
                                          }
                                        : {}),
                                },
                            ],
                        } as any,
                    })
                }
                actions.createDashboardSuccess(dashboard)
            } catch {
                actions.createDashboardFailure('Failed to create the dashboard')
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
