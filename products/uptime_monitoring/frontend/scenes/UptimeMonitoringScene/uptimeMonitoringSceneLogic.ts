import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { uptimeMonitorsCreate, uptimeMonitorsDestroy, uptimeMonitorsList } from '../../generated/api'
import type { CreateUptimeMonitorInputApi, UptimeMonitorApi } from '../../generated/api.schemas'
import type { uptimeMonitoringSceneLogicType } from './uptimeMonitoringSceneLogicType'

// The list is not paginated in the UI yet, so fetch one large page.
const LIST_LIMIT = 200

const NEW_MONITOR_DEFAULTS: CreateUptimeMonitorInputApi = { name: '', url: '', interval_seconds: 300 }

function projectId(): string {
    return String(ApiConfig.getCurrentProjectId())
}

function isHttpUrl(value: string): boolean {
    try {
        return ['http:', 'https:'].includes(new URL(value).protocol)
    } catch {
        return false
    }
}

export const uptimeMonitoringSceneLogic = kea<uptimeMonitoringSceneLogicType>([
    path([
        'products',
        'uptime_monitoring',
        'frontend',
        'scenes',
        'UptimeMonitoringScene',
        'uptimeMonitoringSceneLogic',
    ]),

    actions({
        openCreateModal: true,
        closeCreateModal: true,
        confirmDeleteMonitor: (monitor: UptimeMonitorApi) => ({ monitor }),
    }),

    loaders(({ values }) => ({
        monitors: [
            null as UptimeMonitorApi[] | null,
            {
                loadMonitors: async () => (await uptimeMonitorsList(projectId(), { limit: LIST_LIMIT })).results,
                deleteMonitor: async (monitor: UptimeMonitorApi) => {
                    await uptimeMonitorsDestroy(projectId(), monitor.id)
                    lemonToast.success('Monitor deleted')
                    return (values.monitors ?? []).filter((m) => m.id !== monitor.id)
                },
            },
        ],
    })),

    reducers({
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
    }),

    forms(({ actions, values }) => ({
        newMonitor: {
            defaults: NEW_MONITOR_DEFAULTS,
            errors: ({ name, url }) => ({
                name: !name.trim() ? 'Enter a name' : undefined,
                url: !isHttpUrl(url) ? 'Enter a URL that starts with http:// or https://' : undefined,
            }),
            submit: async (form) => {
                const created = await uptimeMonitorsCreate(projectId(), { ...form, name: form.name.trim() })
                actions.loadMonitorsSuccess([created, ...(values.monitors ?? [])])
                actions.closeCreateModal()
                lemonToast.success('Monitor created')
            },
        },
    })),

    listeners(({ actions }) => ({
        closeCreateModal: () => actions.resetNewMonitor(),
        confirmDeleteMonitor: ({ monitor }) => {
            LemonDialog.open({
                title: `Delete ${monitor.name}?`,
                description: 'This removes the monitor and its settings. You can create it again later.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => actions.deleteMonitor(monitor),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
    })),

    afterMount(({ actions }) => {
        // The scene mounts this logic before it checks the flag, and the API 404s while the flag is off.
        if (featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.UPTIME_MONITORING]) {
            actions.loadMonitors()
        }
    }),
])
