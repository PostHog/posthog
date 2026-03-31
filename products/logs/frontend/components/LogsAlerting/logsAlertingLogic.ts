import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { logsAlertsDestroy, logsAlertsList, logsAlertsPartialUpdate } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertingLogicType } from './logsAlertingLogicType'

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

    afterMount(({ actions }) => {
        actions.loadAlerts()
    }),
])
