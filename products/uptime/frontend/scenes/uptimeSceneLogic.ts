import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { uptimeSceneLogicType } from './uptimeSceneLogicType'

export interface Monitor {
    id: string
    name: string
    url: string
    created_at: string
}

export interface Ping {
    monitor_id: string
    timestamp: string
    latency_ms: number
    status_code: number | null
    outcome: 'success' | 'failure'
}

export const uptimeSceneLogic = kea<uptimeSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        selectMonitor: (monitorId: string | null) => ({ monitorId }),
        pingNow: (monitorId: string) => ({ monitorId }),
    }),

    reducers({
        selectedMonitorId: [
            null as string | null,
            {
                selectMonitor: (_, { monitorId }) => monitorId,
            },
        ],
    }),

    loaders(({ values }) => ({
        monitors: [
            [] as Monitor[],
            {
                loadMonitors: async () => {
                    return await api.get<Monitor[]>(`api/projects/${values.currentProjectId}/uptime/monitors/`)
                },
            },
        ],
        pings: [
            [] as Ping[],
            {
                loadPings: async (monitorId: string) => {
                    return await api.get<Ping[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/${monitorId}/pings/`
                    )
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        createMonitor: {
            defaults: { name: '', url: '' } as { name: string; url: string },
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : null,
                url: !url ? 'URL is required' : null,
            }),
            submit: async ({ name, url }) => {
                const created = await api.create<Monitor>(`api/projects/${values.currentProjectId}/uptime/monitors/`, {
                    name,
                    url,
                })
                lemonToast.success(`Monitor "${created.name}" created`)
                actions.resetCreateMonitor()
                actions.loadMonitors()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        selectMonitor: ({ monitorId }) => {
            if (monitorId) {
                actions.loadPings(monitorId)
            }
        },
        pingNow: async ({ monitorId }) => {
            await api.create(`api/projects/${values.currentProjectId}/uptime/monitors/${monitorId}/ping_now/`, {})
            lemonToast.info('Ping enqueued — refresh in a few seconds')
        },
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'Uptime',
                    name: 'Uptime',
                    path: urls.uptime(),
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadMonitors()
    }),
])
