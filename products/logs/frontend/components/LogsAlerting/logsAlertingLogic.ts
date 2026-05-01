import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    logsAlertsDestroy,
    logsAlertsList,
    logsAlertsPartialUpdate,
    logsAlertsResetCreate,
} from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertingLogicType } from './logsAlertingLogicType'
import { withEnableNotificationGuard } from './logsAlertUtils'

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
        setViewingHistoryAlert: (alert: LogsAlertConfigurationApi | null) => ({ alert }),
        snoozeAlert: (alertId: string, durationMinutes: number) => ({ alertId, durationMinutes }),
        unsnoozeAlert: (alertId: string) => ({ alertId }),
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
        viewingHistoryAlert: [
            null as LogsAlertConfigurationApi | null,
            {
                setViewingHistoryAlert: (_, { alert }) => alert,
            },
        ],
    }),

    loaders(({ values }) => ({
        alerts: [
            [] as LogsAlertConfigurationApi[],
            {
                loadAlerts: async () => {
                    const projectId = String(values.currentTeamId)
                    const response = await logsAlertsList(projectId, { limit: 500 })
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
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
        toggleAlertEnabled: ({ alert }) => {
            withEnableNotificationGuard(
                alert,
                async () => {
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
                () => router.actions.push(urls.logsAlertDetail(alert.id, 'notifications'))
            )
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
        snoozeAlert: async ({ alertId, durationMinutes }) => {
            const projectId = String(values.currentTeamId)
            const snoozeUntil = dayjs().add(durationMinutes, 'minute').toISOString()
            try {
                await logsAlertsPartialUpdate(projectId, alertId, { snooze_until: snoozeUntil })
                lemonToast.success('Alert snoozed')
                actions.loadAlerts()
            } catch {
                lemonToast.error('Failed to snooze alert')
            }
        },
        unsnoozeAlert: async ({ alertId }) => {
            const projectId = String(values.currentTeamId)
            try {
                await logsAlertsPartialUpdate(projectId, alertId, { snooze_until: null })
                lemonToast.success('Alert unsnoozed')
                actions.loadAlerts()
            } catch {
                lemonToast.error('Failed to unsnooze alert')
            }
        },
    })),

    afterMount(({ actions, values, cache }) => {
        actions.loadAlerts()
        cache.disposables.add(() => {
            const intervalId = window.setInterval(() => {
                if (!values.isCreating && values.editingAlert === null && values.viewingHistoryAlert === null) {
                    actions.loadAlerts()
                }
            }, ALERT_POLL_INTERVAL_MS)
            return () => clearInterval(intervalId)
        }, 'pollAlerts')
    }),
])
