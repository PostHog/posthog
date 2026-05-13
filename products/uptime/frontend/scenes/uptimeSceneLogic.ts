import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

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

export type MonitorStatus = 'up' | 'down' | 'no_data'
export type DailyStatus = 'up' | 'degraded' | 'down' | 'no_data'

export interface DailyBucket {
    date: string
    total: number
    failed: number
    status: DailyStatus
}

export interface MonitorSummary {
    id: string
    name: string
    url: string
    created_at: string
    status: MonitorStatus
    uptime_30d: number | null
    avg_latency_24h_ms: number | null
    last_ping_at: string | null
    last_ping_outcome: 'success' | 'failure' | null
    daily_buckets: DailyBucket[]
}

export interface OverallStats {
    total: number
    operational: number
    down: number
    noData: number
    avgUptime: number | null
    avgLatencyMs: number | null
}

export type UptimeSceneActiveTab = 'monitors' | 'alerts'

const DEFAULT_ACTIVE_TAB: UptimeSceneActiveTab = 'monitors'

export const uptimeSceneLogic = kea<uptimeSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setActiveTab: (activeTab: UptimeSceneActiveTab) => ({ activeTab }),
        selectMonitor: (monitorId: string | null) => ({ monitorId }),
        pingNow: (monitorId: string) => ({ monitorId }),
        setCreateModalOpen: (open: boolean) => ({ open }),
        setSuggestModalOpen: (open: boolean) => ({ open }),
        toggleSuggestion: (url: string) => ({ url }),
        clearSelectedSuggestions: true,
        bulkAddSelected: true,
    }),

    reducers({
        activeTab: [
            DEFAULT_ACTIVE_TAB as UptimeSceneActiveTab,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
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
        monitorSummaries: [
            [] as MonitorSummary[],
            {
                loadMonitorSummaries: async () => {
                    return await api.get<MonitorSummary[]>(
                        `api/projects/${values.currentProjectId}/uptime/monitors/summary/`
                    )
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
                actions.loadMonitorSummaries()
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
            actions.loadMonitorSummaries()
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
        overallStats: [
            (s) => [s.monitorSummaries],
            (summaries: MonitorSummary[]): OverallStats => {
                const total = summaries.length
                const operational = summaries.filter((m) => m.status === 'up').length
                const down = summaries.filter((m) => m.status === 'down').length
                const noData = summaries.filter((m) => m.status === 'no_data').length

                // Ping-weighted uptime across all monitors: one rarely-pinged outlier can't drag
                // the figure below a fleet of healthy high-volume monitors. Equivalent to
                // (total successes) / (total checks) over the last 30 days.
                let totalChecks = 0
                let totalFailures = 0
                for (const m of summaries) {
                    for (const bucket of m.daily_buckets) {
                        totalChecks += bucket.total
                        totalFailures += bucket.failed
                    }
                }

                const latencies = summaries.map((m) => m.avg_latency_24h_ms).filter((l): l is number => l !== null)
                return {
                    total,
                    operational,
                    down,
                    noData,
                    avgUptime: totalChecks > 0 ? (totalChecks - totalFailures) / totalChecks : null,
                    avgLatencyMs: latencies.length
                        ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
                        : null,
                }
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        '**/uptime': (_, params) => {
            if (params.activeTab && !equal(params.activeTab, values.activeTab)) {
                actions.setActiveTab(params.activeTab)
            }
        },
    })),

    actionToUrl(({ values }) => {
        const buildURL = (): [string, Record<string, any>, Record<string, any>] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.activeTab === DEFAULT_ACTIVE_TAB) {
                delete searchParams.activeTab
            } else {
                searchParams.activeTab = values.activeTab
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams]
        }
        return {
            setActiveTab: buildURL,
        }
    }),

    afterMount(({ actions }) => {
        actions.loadMonitorSummaries()
        actions.loadSuggestedUrls()
    }),
])
