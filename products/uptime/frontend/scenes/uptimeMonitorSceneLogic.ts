import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { uptimeMonitorSceneLogicType } from './uptimeMonitorSceneLogicType'
import { Monitor, MonitorSummary, Ping } from './uptimeSceneLogic'

export const uptimeMonitorSceneLogic = kea<uptimeMonitorSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeMonitorSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setMonitorId: (id: string | null) => ({ id }),
        pingNow: true,
        setEditModalOpen: (open: boolean) => ({ open }),
        deleteMonitor: true,
    }),

    reducers({
        monitorId: [
            null as string | null,
            {
                setMonitorId: (_, { id }) => id,
            },
        ],
        editModalOpen: [
            false,
            {
                setEditModalOpen: (_, { open }) => open,
            },
        ],
    }),

    loaders(({ values }) => ({
        summary: [
            null as MonitorSummary | null,
            {
                loadSummary: async () => {
                    if (!values.monitorId) {
                        return null
                    }
                    const all = await api.get<MonitorSummary[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/summary/`
                    )
                    return all.find((m) => m.id === values.monitorId) ?? null
                },
            },
        ],
        pings: [
            [] as Ping[],
            {
                loadPings: async () => {
                    if (!values.monitorId) {
                        return []
                    }
                    return await api.get<Ping[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/pings/`
                    )
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        editMonitor: {
            defaults: { name: '', url: '' } as { name: string; url: string },
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : null,
                url: !url ? 'URL is required' : null,
            }),
            submit: async ({ name, url }) => {
                if (!values.monitorId) {
                    return
                }
                const updated = await api.update<Monitor>(
                    `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/`,
                    { name, url }
                )
                lemonToast.success(`Monitor "${updated.name}" updated`)
                actions.setEditModalOpen(false)
                actions.loadSummary()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setMonitorId: () => {
            if (values.monitorId) {
                actions.loadSummary()
                actions.loadPings()
            }
        },
        loadSummarySuccess: ({ summary }) => {
            if (summary) {
                actions.setEditMonitorValues({ name: summary.name, url: summary.url })
            }
        },
        pingNow: async () => {
            if (!values.monitorId) {
                return
            }
            await api.create(
                `api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/ping_now/`,
                {}
            )
            lemonToast.info('Ping enqueued — refresh in a few seconds')
        },
        deleteMonitor: async () => {
            if (!values.monitorId) {
                return
            }
            await api.delete(`api/projects/${values.currentProjectId}/uptime/monitors/${values.monitorId}/`)
            lemonToast.success('Monitor deleted')
            router.actions.push(urls.uptime())
        },
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.summary, s.monitorId],
            (summary: MonitorSummary | null, monitorId: string | null): Breadcrumb[] => [
                { key: 'Uptime', name: 'Uptime', path: urls.uptime() },
                {
                    key: monitorId ?? 'monitor',
                    name: summary?.name ?? 'Monitor',
                },
            ],
        ],
    }),

    urlToAction(({ actions, values }) => ({
        '/uptime/:id': (params) => {
            const id = params.id
            if (id && id !== values.monitorId) {
                actions.setMonitorId(id)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.monitorId) {
            actions.loadSummary()
            actions.loadPings()
        }
    }),
])
