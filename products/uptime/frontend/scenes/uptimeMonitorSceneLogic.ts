import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    uptimeMonitorsDestroy,
    uptimeMonitorsOutagesList,
    uptimeMonitorsPartialUpdate,
    uptimeMonitorsPingsList,
    uptimeMonitorsRetrieve,
} from '../generated/api'
import type { MonitorSummaryDTOApi, OutageDTOApi, PingDTOApi } from '../generated/api.schemas'
import type { uptimeMonitorSceneLogicType } from './uptimeMonitorSceneLogicType'

export const uptimeMonitorSceneLogic = kea<uptimeMonitorSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeMonitorSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setMonitorId: (id: string | null) => ({ id }),
        setEditModalOpen: (open: boolean) => ({ open }),
        confirmDeleteMonitor: true,
        cancelDeleteMonitor: true,
        deleteMonitor: true,
        deleteMonitorSuccess: true,
        deleteMonitorFailure: true,
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
        deleteConfirmOpen: [
            false,
            {
                confirmDeleteMonitor: () => true,
                cancelDeleteMonitor: () => false,
                deleteMonitorSuccess: () => false,
            },
        ],
        monitorDeleting: [
            false,
            {
                deleteMonitor: () => true,
                deleteMonitorSuccess: () => false,
                deleteMonitorFailure: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        summary: [
            null as MonitorSummaryDTOApi | null,
            {
                loadSummary: async () => {
                    if (!values.monitorId) {
                        return null
                    }
                    try {
                        return await uptimeMonitorsRetrieve(String(values.currentProjectId), values.monitorId)
                    } catch (err: any) {
                        // 404 from retrieve = monitor genuinely gone (deleted, wrong id). Render the
                        // not-found state rather than letting the loader explode.
                        if (err?.status === 404) {
                            return null
                        }
                        throw err
                    }
                },
            },
        ],
        pings: [
            [] as PingDTOApi[],
            {
                loadPings: async () => {
                    if (!values.monitorId) {
                        return []
                    }
                    return await uptimeMonitorsPingsList(String(values.currentProjectId), values.monitorId)
                },
            },
        ],
        outages: [
            [] as OutageDTOApi[],
            {
                loadOutages: async () => {
                    if (!values.monitorId) {
                        return []
                    }
                    return await uptimeMonitorsOutagesList(String(values.currentProjectId), values.monitorId)
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
                const updated = await uptimeMonitorsPartialUpdate(String(values.currentProjectId), values.monitorId, {
                    name,
                    url,
                })
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
                actions.loadOutages()
            }
        },
        setEditModalOpen: ({ open }) => {
            // Reopening starts from the monitor's current values — no stale edits or errors.
            if (open && values.summary) {
                actions.resetEditMonitor()
                actions.setEditMonitorValues({ name: values.summary.name, url: values.summary.url })
            }
        },
        deleteMonitor: async () => {
            if (!values.monitorId) {
                return
            }
            try {
                await uptimeMonitorsDestroy(String(values.currentProjectId), values.monitorId)
                lemonToast.success('Monitor deleted')
                actions.deleteMonitorSuccess()
                router.actions.push(urls.uptime())
            } catch {
                lemonToast.error('Failed to delete monitor')
                actions.deleteMonitorFailure()
            }
        },
        submitEditMonitorFailure: ({ error }) => {
            if (error?.message !== 'Validation Failed') {
                lemonToast.error('Failed to update monitor')
            }
        },
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.summary, s.monitorId],
            (summary: MonitorSummaryDTOApi | null, monitorId: string | null): Breadcrumb[] => [
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
            actions.loadOutages()
        }
    }),
])
