import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { logsAlertsDestroy, logsAlertsList, logsAlertsPartialUpdate } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertingLogicType } from './logsAlertingLogicType'

const ALERT_POLL_INTERVAL_MS = 30_000

export const logsAlertingLogic = kea<logsAlertingLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsAlerting', 'logsAlertingLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setEditingAlert: (alert: LogsAlertConfigurationApi | null) => ({ alert }),
        setIsCreating: (isCreating: boolean) => ({ isCreating }),
        deleteAlert: (id: string) => ({ id }),
        toggleAlertEnabled: (alert: LogsAlertConfigurationApi) => ({ alert }),
    }),

    reducers({
        editingAlert: [
            null as LogsAlertConfigurationApi | null,
            {
                setEditingAlert: (_, { alert }) => alert,
                setIsCreating: () => null,
            },
        ],
        isCreating: [
            false,
            {
                setIsCreating: (_, { isCreating }) => isCreating,
                setEditingAlert: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        alerts: [
            [] as LogsAlertConfigurationApi[],
            {
                loadAlerts: async () => {
                    const projectId = String(values.currentTeamId)
                    const response = await logsAlertsList(projectId)
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        loadAlertsSuccess: () => {
            const params = router.values.searchParams
            if (params.alertId && typeof params.alertId === 'string') {
                const alert = values.alerts.find((a) => a.id === params.alertId)
                if (alert) {
                    actions.setEditingAlert(alert)
                }
                // Clear alertId from URL regardless of whether we found the alert
                const { alertId: _, ...rest } = router.values.searchParams
                router.actions.replace(router.values.location.pathname, rest, router.values.hashParams)
            }
        },
        deleteAlert: async ({ id }) => {
            const projectId = String(values.currentTeamId)
            try {
                await logsAlertsDestroy(projectId, id)
                lemonToast.success('Alert deleted')
                actions.loadAlerts()
            } catch {
                lemonToast.error('Failed to delete alert')
            }
        },
        toggleAlertEnabled: async ({ alert }) => {
            const projectId = String(values.currentTeamId)
            try {
                await logsAlertsPartialUpdate(projectId, alert.id, {
                    enabled: !(alert.enabled ?? true),
                })
                actions.loadAlerts()
            } catch {
                lemonToast.error('Failed to update alert')
            }
        },
    })),

    afterMount(({ actions, values, cache }) => {
        actions.loadAlerts()
        cache.disposables.add(() => {
            const intervalId = window.setInterval(() => {
                if (!values.isCreating && values.editingAlert === null) {
                    actions.loadAlerts()
                }
            }, ALERT_POLL_INTERVAL_MS)
            return () => clearInterval(intervalId)
        }, 'pollAlerts')
    }),
])
