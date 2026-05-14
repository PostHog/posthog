import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { openPostIncidentUpdateDialog, openResolveIncidentDialog } from './incidentActions'
import type { uptimeSceneLogicType } from './uptimeSceneLogicType'

export type MonitorMode = 'auto' | 'manual'

export interface Monitor {
    id: string
    name: string
    url: string | null
    mode: MonitorMode
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
    url: string | null
    mode: MonitorMode
    created_at: string
    status: MonitorStatus
    uptime_90d: number | null
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

export type IncidentUpdateKeyword = 'investigating' | 'identified' | 'fixing' | 'monitoring' | 'resolved' | 'update'

export interface IncidentUpdate {
    id: string
    keyword: IncidentUpdateKeyword
    message: string
    posted_at: string
    posted_by_id: number | null
}

export interface Incident {
    id: string
    monitor_id: string
    name: string
    description: string
    started_at: string
    resolved_at: string | null
    resolution_note: string
    updates: IncidentUpdate[]
    created_at: string
    updated_at: string
}

export interface Outage {
    monitor_id: string
    started_at: string
    resolved_at: string | null
    fail_count: number
    last_status_code: number | null
}

export type UptimeSceneActiveTab = 'monitors' | 'incidents' | 'alerts' | 'status_pages'

const DEFAULT_ACTIVE_TAB: UptimeSceneActiveTab = 'monitors'

export const uptimeSceneLogic = kea<uptimeSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setActiveTab: (activeTab: UptimeSceneActiveTab) => ({ activeTab }),
        pingNow: (monitorId: string) => ({ monitorId }),
        setCreateModalOpen: (open: boolean) => ({ open }),
        setCreateWizardStep: (step: 'mode' | 'details') => ({ step }),
        setSuggestModalOpen: (open: boolean) => ({ open }),
        toggleSuggestion: (url: string) => ({ url }),
        clearSelectedSuggestions: true,
        bulkAddSelected: true,
        startEditing: (monitor: MonitorSummary) => ({ monitor }),
        stopEditing: true,
        confirmDeleteMonitor: (monitor: { id: string; name: string }) => ({ monitor }),
        deleteMonitor: (monitorId: string) => ({ monitorId }),
        quickAddSuggestion: (suggestion: SuggestedUrl) => ({ suggestion }),
        reorderMonitors: (orderedIds: string[]) => ({ orderedIds }),
        startEditingIncident: (incident: Incident) => ({ incident }),
        stopEditingIncident: true,
        promptResolveIncident: (incident: Incident) => ({ incident }),
        promptPostIncidentUpdate: (incident: Incident) => ({ incident }),
        reopenIncident: (incidentId: string) => ({ incidentId }),
        confirmDeleteIncident: (incident: { id: string; name: string }) => ({ incident }),
        deleteIncident: (incidentId: string) => ({ incidentId }),
    }),

    reducers({
        activeTab: [
            DEFAULT_ACTIVE_TAB as UptimeSceneActiveTab,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        createModalOpen: [
            false,
            {
                setCreateModalOpen: (_, { open }) => open,
            },
        ],
        // Two-step wizard: 'mode' (pick auto vs manual) then 'details' (name + url).
        // Resets to 'mode' every time the modal opens so the user always starts at step 1.
        createWizardStep: [
            'mode' as 'mode' | 'details',
            {
                setCreateWizardStep: (_, { step }) => step,
                setCreateModalOpen: (state, { open }) => (open ? 'mode' : state),
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
        editingMonitorId: [
            null as string | null,
            {
                startEditing: (_, { monitor }) => monitor.id,
                stopEditing: () => null,
            },
        ],
        // Incident id being edited from this scene's listing; null = closed.
        editingIncidentId: [
            null as string | null,
            {
                startEditingIncident: (_, { incident }) => incident.id,
                stopEditingIncident: () => null,
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
        incidents: [
            [] as Incident[],
            {
                loadIncidents: async () => {
                    return await api.get<Incident[]>(`api/projects/${values.currentProjectId}/uptime/incidents/`)
                },
            },
        ],
    })),

    // Optimistic reorder lives in a separate reducers() block — kea-loaders only treats
    // async functions inside the loaders inner object as cases. Putting a sync reducer
    // case there silently no-ops, which is what made the dragged tile snap back.
    reducers({
        monitorSummaries: {
            reorderMonitors: (state: MonitorSummary[], { orderedIds }: { orderedIds: string[] }) => {
                const byId = new Map(state.map((m) => [m.id, m]))
                const reordered: MonitorSummary[] = []
                for (const id of orderedIds) {
                    const found = byId.get(id)
                    if (found) {
                        reordered.push(found)
                        byId.delete(id)
                    }
                }
                // Anything the caller didn't include keeps its position at the end.
                for (const remaining of byId.values()) {
                    reordered.push(remaining)
                }
                return reordered
            },
        },
    }),

    forms(({ values, actions }) => ({
        createMonitor: {
            defaults: { name: '', url: '', mode: 'auto' } as { name: string; url: string; mode: MonitorMode },
            errors: ({ name, url, mode }) => ({
                name: !name ? 'Name is required' : null,
                // URL is only required in auto mode — manual monitors can track services
                // without a public health endpoint.
                url: mode === 'auto' && !url ? 'URL is required for auto mode' : null,
            }),
            submit: async ({ name, url, mode }) => {
                const created = await api.create<Monitor>(`api/projects/${values.currentProjectId}/uptime/monitors/`, {
                    name,
                    // Empty string would 400 on URLField — send null for manual mode without a URL.
                    url: url || null,
                    mode,
                })
                lemonToast.success(`Monitor "${created.name}" created`)
                actions.resetCreateMonitor()
                actions.setCreateModalOpen(false)
                actions.loadMonitorSummaries()
                actions.loadSuggestedUrls()
            },
        },
        editMonitor: {
            defaults: { name: '', url: '', mode: 'auto' } as { name: string; url: string; mode: MonitorMode },
            errors: ({ name, url, mode }) => ({
                name: !name ? 'Name is required' : null,
                // URL only required for auto-mode monitors.
                url: mode === 'auto' && !url ? 'URL is required for auto mode' : null,
            }),
            submit: async ({ name, url, mode }) => {
                const id = values.editingMonitorId
                if (!id) {
                    return
                }
                const updated = await api.update<Monitor>(
                    `api/projects/${values.currentProjectId}/uptime/monitors/${id}/`,
                    { name, url: url || null, mode }
                )
                lemonToast.success(`Monitor "${updated.name}" updated`)
                actions.stopEditing()
                actions.loadMonitorSummaries()
            },
        },
        editIncident: {
            defaults: { name: '', description: '', resolution_note: '' } as {
                name: string
                description: string
                resolution_note: string
            },
            errors: ({ name, resolution_note }) => ({
                name: !name ? 'Name is required' : null,
                resolution_note:
                    values.editingIncident?.resolved_at && !resolution_note?.trim()
                        ? 'A resolution note is required'
                        : null,
            }),
            submit: async ({ name, description, resolution_note }) => {
                const id = values.editingIncidentId
                if (!id) {
                    return
                }
                const payload: Record<string, string> = { name, description }
                if (values.editingIncident?.resolved_at) {
                    payload.resolution_note = resolution_note
                }
                await api.update<Incident>(`api/projects/${values.currentProjectId}/uptime/incidents/${id}/`, payload)
                lemonToast.success('Declared incident updated')
                actions.stopEditingIncident()
                actions.loadIncidents()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        pingNow: async ({ monitorId }) => {
            await api.create(`api/projects/${values.currentProjectId}/uptime/monitors/${monitorId}/ping_now/`, {})
            lemonToast.info('Ping enqueued — refresh in a few seconds')
        },
        startEditing: ({ monitor }) => {
            actions.setEditMonitorValues({ name: monitor.name, url: monitor.url ?? '', mode: monitor.mode })
        },
        confirmDeleteMonitor: ({ monitor }) => {
            LemonDialog.open({
                title: `Delete monitor "${monitor.name}"?`,
                description: 'Historical pings stay in the audit log; the monitor card disappears from the list.',
                primaryButton: {
                    children: 'Delete monitor',
                    status: 'danger',
                    onClick: () => actions.deleteMonitor(monitor.id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        deleteMonitor: async ({ monitorId }) => {
            await api.delete(`api/projects/${values.currentProjectId}/uptime/monitors/${monitorId}/`)
            lemonToast.success('Monitor deleted')
            actions.loadMonitorSummaries()
            actions.loadSuggestedUrls()
        },
        reorderMonitors: async ({ orderedIds }) => {
            try {
                await api.create(`api/projects/${values.currentProjectId}/uptime/monitors/reorder/`, {
                    ordered_ids: orderedIds,
                })
            } catch (err) {
                // Backend rejected the new order — refetch authoritative list so the UI snaps back.
                lemonToast.error("Couldn't save the new order")
                actions.loadMonitorSummaries()
                throw err
            }
        },
        quickAddSuggestion: async ({ suggestion }) => {
            const created = await api.create<Monitor>(`api/projects/${values.currentProjectId}/uptime/monitors/`, {
                name: suggestion.host,
                url: suggestion.url,
            })
            lemonToast.success(`Now monitoring ${created.name}`)
            // Send the user straight to the new monitor's detail page — clearer feedback than
            // hoping the list reload finishes before the empty state re-evaluates, which left
            // the new monitor invisible behind a re-rendered ghost tile.
            router.actions.push(urls.uptimeMonitor(created.id))
            actions.loadSuggestedUrls()
        },
        startEditingIncident: ({ incident }) => {
            actions.setEditIncidentValues({
                name: incident.name,
                description: incident.description,
                resolution_note: incident.resolution_note,
            })
        },
        promptResolveIncident: ({ incident }) => {
            openResolveIncidentDialog({
                incident,
                projectId: values.currentProjectId as string,
                onResolved: () => actions.loadIncidents(),
            })
        },
        promptPostIncidentUpdate: ({ incident }) => {
            openPostIncidentUpdateDialog({
                incident,
                projectId: values.currentProjectId as string,
                onPosted: () => actions.loadIncidents(),
            })
        },
        reopenIncident: async ({ incidentId }) => {
            await api.create(`api/projects/${values.currentProjectId}/uptime/incidents/${incidentId}/reopen/`, {})
            lemonToast.info('Declared incident reopened')
            actions.loadIncidents()
        },
        confirmDeleteIncident: ({ incident }) => {
            LemonDialog.open({
                title: `Delete declared incident "${incident.name}"?`,
                description: 'This permanently removes the incident.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => actions.deleteIncident(incident.id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        deleteIncident: async ({ incidentId }) => {
            await api.delete(`api/projects/${values.currentProjectId}/uptime/incidents/${incidentId}/`)
            lemonToast.success('Declared incident deleted')
            actions.loadIncidents()
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
        editingIncident: [
            (s) => [s.incidents, s.editingIncidentId],
            (incidents: Incident[], id: string | null): Incident | null => {
                if (!id) {
                    return null
                }
                return incidents.find((i) => i.id === id) ?? null
            },
        ],
        ongoingIncidents: [
            (s) => [s.incidents],
            (incidents: Incident[]): Incident[] => incidents.filter((i) => i.resolved_at === null),
        ],
        resolvedIncidents: [
            (s) => [s.incidents],
            (incidents: Incident[]): Incident[] => incidents.filter((i) => i.resolved_at !== null),
        ],
        ongoingIncidentsCount: [(s) => [s.ongoingIncidents], (ongoing: Incident[]): number => ongoing.length],
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
        actions.loadIncidents()
    }),
])
