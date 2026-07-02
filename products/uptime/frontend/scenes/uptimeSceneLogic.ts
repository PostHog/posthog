import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    uptimeMonitorsCreate,
    uptimeMonitorsDestroy,
    uptimeMonitorsPartialUpdate,
    uptimeMonitorsSummaryList,
} from '../generated/api'
import type { MonitorSummaryDTOApi } from '../generated/api.schemas'
import type { uptimeSceneLogicType } from './uptimeSceneLogicType'

export interface OverallStats {
    total: number
    operational: number
    down: number
    noData: number
    avgUptime: number | null
    avgLatencyMs: number | null
}

export const uptimeSceneLogic = kea<uptimeSceneLogicType>([
    path(['products', 'uptime', 'frontend', 'scenes', 'uptimeSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setCreateModalOpen: (open: boolean) => ({ open }),
        startEditing: (monitor: MonitorSummaryDTOApi) => ({ monitor }),
        stopEditing: true,
        confirmDeleteMonitor: (monitor: { id: string; name: string }) => ({ monitor }),
        deleteMonitor: (monitorId: string) => ({ monitorId }),
    }),

    reducers({
        createModalOpen: [
            false,
            {
                setCreateModalOpen: (_, { open }) => open,
            },
        ],
        editingMonitorId: [
            null as string | null,
            {
                startEditing: (_, { monitor }) => monitor.id,
                stopEditing: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        monitorSummaries: [
            [] as MonitorSummaryDTOApi[],
            {
                loadMonitorSummaries: async () => {
                    return await uptimeMonitorsSummaryList(String(values.currentProjectId))
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
                const created = await uptimeMonitorsCreate(String(values.currentProjectId), { name, url })
                lemonToast.success(`Monitor "${created.name}" created`)
                actions.resetCreateMonitor()
                actions.setCreateModalOpen(false)
                actions.loadMonitorSummaries()
            },
        },
        editMonitor: {
            defaults: { name: '', url: '' } as { name: string; url: string },
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : null,
                url: !url ? 'URL is required' : null,
            }),
            submit: async ({ name, url }) => {
                const id = values.editingMonitorId
                if (!id) {
                    return
                }
                const updated = await uptimeMonitorsPartialUpdate(String(values.currentProjectId), id, { name, url })
                lemonToast.success(`Monitor "${updated.name}" updated`)
                actions.stopEditing()
                actions.loadMonitorSummaries()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        startEditing: ({ monitor }) => {
            actions.setEditMonitorValues({ name: monitor.name, url: monitor.url })
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
            await uptimeMonitorsDestroy(String(values.currentProjectId), monitorId)
            lemonToast.success('Monitor deleted')
            actions.loadMonitorSummaries()
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
        overallStats: [
            (s) => [s.monitorSummaries],
            (summaries: MonitorSummaryDTOApi[]): OverallStats => {
                const total = summaries.length
                const operational = summaries.filter((m) => m.status === 'up').length
                const down = summaries.filter((m) => m.status === 'down').length
                const noData = summaries.filter((m) => m.status === 'no_data').length

                // Ping-weighted uptime across all monitors: one rarely-pinged outlier can't drag
                // the figure below a fleet of healthy high-volume monitors. Equivalent to
                // (total successes) / (total checks) over the last 90 days.
                let totalChecks = 0
                let totalFailures = 0
                for (const m of summaries) {
                    for (const bucket of m.daily_buckets) {
                        totalChecks += bucket.total
                        totalFailures += bucket.failed
                    }
                }

                const latencies = summaries
                    .map((m) => m.avg_latency_24h_ms)
                    .filter((l): l is number => l !== null && l !== undefined)
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

    afterMount(({ actions }) => {
        actions.loadMonitorSummaries()
    }),
])
