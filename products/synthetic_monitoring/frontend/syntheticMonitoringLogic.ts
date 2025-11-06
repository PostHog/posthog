import { actions, connect, kea, listeners, path, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { syntheticMonitoringLogicType } from './syntheticMonitoringLogicType'
import { SyntheticMonitor } from './types'

export const syntheticMonitoringLogic = kea<syntheticMonitoringLogicType>([
    path(['products', 'synthetic_monitoring', 'frontend', 'syntheticMonitoringLogic']),
    connect({
        values: [userLogic, ['user']],
        actions: [sceneLogic, ['newTab']],
    }),
    actions({
        loadMonitors: true,
        deleteMonitor: (id: string) => ({ id }),
        pauseMonitor: (id: string) => ({ id }),
        resumeMonitor: (id: string) => ({ id }),
        createAlertWorkflow: (id: string) => ({ id }),
    }),
    lazyLoaders(({ values }) => ({
        monitors: [
            [] as SyntheticMonitor[],
            {
                loadMonitors: async () => {
                    const response = await api.syntheticMonitoring.list()
                    return response.results
                },
                deleteMonitor: async ({ id }) => {
                    await api.syntheticMonitoring.delete(id)
                    lemonToast.success('Monitor deleted successfully')
                    return values.monitors.filter((m) => m.id !== id)
                },
                pauseMonitor: async ({ id }) => {
                    const updated = await api.syntheticMonitoring.update(id, { enabled: false })
                    lemonToast.success('Monitor paused')
                    return values.monitors.map((m) => (m.id === id ? updated : m))
                },
                resumeMonitor: async ({ id }) => {
                    const updated = await api.syntheticMonitoring.update(id, { enabled: true })
                    lemonToast.success('Monitor resumed')
                    return values.monitors.map((m) => (m.id === id ? updated : m))
                },
            },
        ],
    })),
    selectors({
        activeMonitors: [(s) => [s.monitors], (monitors): SyntheticMonitor[] => monitors.filter((m) => m.enabled)],
        pausedMonitors: [(s) => [s.monitors], (monitors): SyntheticMonitor[] => monitors.filter((m) => !m.enabled)],
    }),
    listeners(({ actions }) => ({
        createAlertWorkflow: async ({ id }) => {
            // Navigate to workflows page with monitor ID pre-filled
            actions.newTab(urls.workflowNew() + `?monitorId=${id}`)
        },
    })),
])
