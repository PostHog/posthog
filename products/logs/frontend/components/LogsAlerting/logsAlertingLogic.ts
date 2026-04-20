import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    logsAlertsDestroy,
    logsAlertsList,
    logsAlertsPartialUpdate,
    logsAlertsResetCreate,
} from 'products/logs/frontend/generated/api'
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
        resetAlert: (id: string) => ({ id }),
        setResettingAlertId: (id: string, resetting: boolean) => ({ id, resetting }),
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
        resettingAlertIds: [
            new Set<string>(),
            {
                setResettingAlertId: (state, { id, resetting }) =>
                    resetting ? new Set([...state, id]) : new Set([...state].filter((x) => x !== id)),
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
        resetAlert: async ({ id }) => {
            const projectId = String(values.currentTeamId)
            actions.setResettingAlertId(id, true)
            try {
                const updated = await logsAlertsResetCreate(projectId, id)
                lemonToast.success('Alert reset — next check will run shortly.')
                // Refresh the modal's snapshot so the "broken" banner disappears without
                // waiting for the list reload to round-trip.
                if (values.editingAlert?.id === id) {
                    actions.setEditingAlert(updated)
                }
                actions.loadAlerts()
            } catch {
                lemonToast.error('Failed to reset alert')
            } finally {
                actions.setResettingAlertId(id, false)
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
