import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import {
    logsAlertsChecksList,
    logsAlertsDestroy,
    logsAlertsList,
    logsAlertsPartialUpdate,
} from 'products/logs/frontend/generated/api'
import {
    LogsAlertCheckApi,
    LogsAlertsChecksListOutcome,
    LogsAlertConfigurationApi,
} from 'products/logs/frontend/generated/api.schemas'

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
        viewCheckHistory: (alert: LogsAlertConfigurationApi) => ({ alert }),
        closeCheckHistory: true,
        setCheckHistoryOutcome: (outcome: string) => ({ outcome }),
        loadCheckHistoryPage: (url: string) => ({ url }),
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
        checkHistoryAlert: [
            null as LogsAlertConfigurationApi | null,
            {
                viewCheckHistory: (_, { alert }) => alert,
                closeCheckHistory: () => null,
            },
        ],
        checkHistoryOutcome: [
            'all' as string,
            {
                setCheckHistoryOutcome: (_, { outcome }) => outcome,
                closeCheckHistory: () => 'all',
            },
        ],
        checkHistoryNext: [
            null as string | null,
            {
                loadCheckHistorySuccess: (_, { checkHistory }) => checkHistory.next ?? null,
                closeCheckHistory: () => null,
            },
        ],
        checkHistoryPrevious: [
            null as string | null,
            {
                loadCheckHistorySuccess: (_, { checkHistory }) => checkHistory.previous ?? null,
                closeCheckHistory: () => null,
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
        checkHistory: [
            {
                count: 0,
                results: [] as LogsAlertCheckApi[],
                next: null as string | null,
                previous: null as string | null,
            },
            {
                loadCheckHistory: async () => {
                    const alert = values.checkHistoryAlert
                    if (!alert) {
                        return { results: [], next: null, previous: null }
                    }
                    const projectId = String(values.currentTeamId)
                    const outcome = values.checkHistoryOutcome
                    return await logsAlertsChecksList(
                        projectId,
                        alert.id,
                        outcome !== 'all' ? { outcome: outcome as LogsAlertsChecksListOutcome } : {}
                    )
                },
                loadCheckHistoryPage: async ({ url }) => {
                    return await api.get(url)
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
        viewCheckHistory: () => {
            actions.loadCheckHistory()
        },
        setCheckHistoryOutcome: () => {
            actions.loadCheckHistory()
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
