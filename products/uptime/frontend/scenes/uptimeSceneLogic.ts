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

export interface SuggestedUrl {
    url: string
    host: string
    event_count: number
    unique_paths: number
    last_seen: string
}

export const uptimeSceneLogic = kea<uptimeSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        selectMonitor: (monitorId: string | null) => ({ monitorId }),
        pingNow: (monitorId: string) => ({ monitorId }),
        setCreateModalOpen: (open: boolean) => ({ open }),
        setSuggestModalOpen: (open: boolean) => ({ open }),
        toggleSuggestion: (url: string) => ({ url }),
        clearSelectedSuggestions: true,
        bulkAddSelected: true,
    }),

    reducers({
        selectedMonitorId: [
            null as string | null,
            {
                selectMonitor: (_, { monitorId }) => monitorId,
            },
        ],
        createModalOpen: [
            false,
            {
                setCreateModalOpen: (_, { open }) => open,
            },
        ],
        suggestModalOpen: [
            false,
            {
                setSuggestModalOpen: (_, { open }) => open,
            },
        ],
        selectedSuggestions: [
            [] as string[],
            {
                toggleSuggestion: (state, { url }) =>
                    state.includes(url) ? state.filter((u) => u !== url) : [...state, url],
                clearSelectedSuggestions: () => [],
                setSuggestModalOpen: (state, { open }) => (open ? state : []),
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
        suggestedUrls: [
            [] as SuggestedUrl[],
            {
                loadSuggestedUrls: async () => {
                    return await api.get<SuggestedUrl[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/suggested_urls/`
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
                actions.setCreateModalOpen(false)
                actions.loadMonitors()
                actions.loadSuggestedUrls()
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
        bulkAddSelected: async () => {
            const selected = values.selectedSuggestionsAsItems
            if (selected.length === 0) {
                return
            }
            const created = await api.create<Monitor[]>(
                `api/projects/${values.currentProjectId}/uptime/monitors/bulk_create/`,
                { monitors: selected }
            )
            lemonToast.success(`Added ${created.length} monitor${created.length === 1 ? '' : 's'}`)
            actions.setSuggestModalOpen(false)
            actions.loadMonitors()
            actions.loadSuggestedUrls()
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
        topSuggestedUrls: [
            (s) => [s.suggestedUrls],
            (suggested: SuggestedUrl[]): SuggestedUrl[] => suggested.slice(0, 6),
        ],
        selectedSuggestionsAsItems: [
            (s) => [s.suggestedUrls, s.selectedSuggestions],
            (suggested: SuggestedUrl[], selected: string[]): { name: string; url: string }[] => {
                const byUrl = new Map(suggested.map((s) => [s.url, s]))
                return selected
                    .map((url) => byUrl.get(url))
                    .filter((s): s is SuggestedUrl => s !== undefined)
                    .map((s) => ({ name: s.host, url: s.url }))
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadMonitors()
        actions.loadSuggestedUrls()
    }),
])
