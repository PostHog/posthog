import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { LogSeverityLevel } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { logsAlertEventHistoryLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertEventHistoryLogic'
import {
    buildFormDefaults,
    logsAlertFormLogic,
} from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { logsAlertingLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertingLogic'
import { logsAlertNotificationLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertNotificationLogic'
import {
    SNOOZE_DURATIONS,
    withEnableNotificationGuard,
} from 'products/logs/frontend/components/LogsAlerting/logsAlertUtils'
import {
    logsAlertsDestroy,
    logsAlertsPartialUpdate,
    logsAlertsResetCreate,
    logsAlertsRetrieve,
} from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertDetailSceneLogicType } from './logsAlertDetailSceneLogicType'

export type LogsAlertDetailTab = 'configuration' | 'notifications' | 'history' | 'logs'
const VALID_TABS: LogsAlertDetailTab[] = ['configuration', 'notifications', 'history', 'logs']
const DEFAULT_TAB: LogsAlertDetailTab = 'configuration'

export { SNOOZE_DURATIONS }

export interface LogsAlertDetailSceneLogicProps {
    id: string
}

export const logsAlertDetailSceneLogic = kea<logsAlertDetailSceneLogicType>([
    path((key) => ['products', 'logs', 'frontend', 'scenes', 'LogsAlertDetailScene', 'logsAlertDetailSceneLogic', key]),
    props({} as LogsAlertDetailSceneLogicProps),
    key((props) => props.id),

    connect((props: LogsAlertDetailSceneLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            logsAlertFormLogic({ alert: { id: props.id } as LogsAlertConfigurationApi }),
            ['alertFormChanged'],
        ],
        actions: [
            logsAlertFormLogic({ alert: { id: props.id } as LogsAlertConfigurationApi }),
            ['submitAlertFormSuccess', 'resetAlertForm'],
            logsAlertNotificationLogic({ alertId: props.id }),
            ['loadExistingHogFunctionsSuccess'],
            logsAlertEventHistoryLogic({ alertId: props.id }),
            ['loadEvents'],
            logsAlertingLogic,
            ['loadAlerts'],
        ],
    })),

    actions({
        setActiveTab: (tab: LogsAlertDetailTab) => ({ tab }),
        renameAlert: (name: string) => ({ name }),
        patchAlertLocally: (patch: Partial<LogsAlertConfigurationApi>) => ({ patch }),
        toggleEnabled: true,
        snoozeAlert: (durationMinutes: number) => ({ durationMinutes }),
        unsnoozeAlert: true,
        resetAlert: true,
        deleteAlert: true,
    }),

    reducers({
        alert: {
            patchAlertLocally: (state, { patch }) => (state ? { ...state, ...patch } : null),
        },
        activeTab: [
            DEFAULT_TAB as LogsAlertDetailTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        sparkline7dFetched: [
            false as boolean,
            {
                loadSparkline7dSuccess: () => true,
                loadSparkline7dFailure: () => true,
                submitAlertFormSuccess: () => false,
            },
        ],
    }),

    loaders(({ values, props }) => ({
        alert: [
            null as LogsAlertConfigurationApi | null,
            {
                loadAlert: async () => logsAlertsRetrieve(String(values.currentTeamId), props.id),
            },
        ],
        sparkline7d: [
            [] as any[],
            {
                loadSparkline7d: async () => {
                    if (!values.alert) {
                        return []
                    }
                    const filters = (values.alert.filters ?? {}) as Record<string, unknown>
                    return api.logs.sparkline({
                        query: {
                            dateRange: { date_from: '-7d', date_to: null },
                            severityLevels: ((filters.severityLevels as string[] | undefined) ??
                                []) as LogSeverityLevel[],
                            serviceNames: (filters.serviceNames as string[] | undefined) ?? [],
                            filterGroup: (filters.filterGroup as any) ?? { type: 'AND', values: [] },
                            sparklineBreakdownBy: 'severity',
                        },
                    })
                },
            },
        ],
    })),

    selectors({
        alertId: [() => [(_, props) => props.id], (id: string): string => id],

        breadcrumbs: [
            (s) => [s.alert],
            (alert: LogsAlertConfigurationApi | null): Breadcrumb[] => [
                {
                    key: Scene.Logs,
                    name: 'Logs',
                    path: `${urls.logs()}?activeTab=alerts`,
                    iconType: 'logs',
                },
                {
                    key: Scene.LogsAlertDetail,
                    name: alert?.name ?? 'Alert',
                    iconType: 'logs',
                },
            ],
        ],

        sparkline7dSeries: [
            (s) => [s.sparkline7d],
            (rows: any[]): { series: SparklineTimeSeries[]; labels: string[] } => {
                if (!rows.length) {
                    return { series: [], labels: [] }
                }
                const timeIndex = new Map<string, number>()
                rows.forEach((row) => {
                    if (!timeIndex.has(row.time)) {
                        timeIndex.set(row.time, timeIndex.size)
                    }
                })
                const times = Array.from(timeIndex.keys())
                const bucketMap = new Map<string, number[]>()
                rows.forEach((row) => {
                    if (row.severity === '(no value)') {
                        return
                    }
                    if (!bucketMap.has(row.severity)) {
                        bucketMap.set(row.severity, Array(times.length).fill(0))
                    }
                    bucketMap.get(row.severity)![timeIndex.get(row.time)!] += row.count
                })
                const severityColor: Record<string, string> = {
                    ERROR: 'danger',
                    WARN: 'warning',
                    INFO: 'success',
                    DEBUG: 'muted',
                }
                const series: SparklineTimeSeries[] = Array.from(bucketMap.entries()).map(([sev, values]) => ({
                    name: sev,
                    values,
                    color: severityColor[sev] ?? 'muted',
                }))
                const totalPerSlot = Array(times.length).fill(0)
                for (const vals of bucketMap.values()) {
                    vals.forEach((v, i) => (totalPerSlot[i] += v))
                }
                const quietValues = totalPerSlot.map((total) => (total === 0 ? 1 : 0))
                if (quietValues.some(Boolean)) {
                    series.push({ name: 'Quiet', values: quietValues, color: 'border' })
                }
                const labels = times.map((t) => dayjs(t).format('MMM D, HH:mm'))
                return { series, labels }
            },
        ],

        logsViewerUrl: [
            (s) => [s.alert],
            (alert: LogsAlertConfigurationApi | null): string => {
                if (!alert) {
                    return `${urls.logs()}?activeTab=viewer`
                }
                const filters = (alert.filters ?? {}) as Record<string, unknown>
                const params: Record<string, string> = { activeTab: 'viewer' }
                const severityLevels = filters.severityLevels as string[] | undefined
                const serviceNames = filters.serviceNames as string[] | undefined
                const filterGroup = filters.filterGroup as object | undefined
                if (severityLevels?.length) {
                    params.severityLevels = JSON.stringify(severityLevels)
                }
                if (serviceNames?.length) {
                    params.serviceNames = JSON.stringify(serviceNames)
                }
                if (filterGroup) {
                    params.filterGroup = JSON.stringify(filterGroup)
                }
                const query = new URLSearchParams(params).toString()
                return `${urls.logs()}?${query}`
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        submitAlertFormSuccess: () => {
            actions.loadAlert()
        },
        loadExistingHogFunctionsSuccess: () => {
            if (!values.alertFormChanged) {
                actions.loadAlert()
            }
        },
        loadAlertSuccess: () => {
            if (values.alert) {
                actions.resetAlertForm(buildFormDefaults(values.alert))
            }
            if (!values.sparkline7dFetched) {
                actions.loadSparkline7d()
            }
            actions.loadEvents()
        },
        renameAlert: async ({ name }) => {
            try {
                await logsAlertsPartialUpdate(String(values.currentTeamId), props.id, { name })
                actions.patchAlertLocally({ name })
            } catch {
                lemonToast.error('Failed to rename alert')
                actions.loadAlert()
            }
        },
        toggleEnabled: () => {
            if (!values.alert) {
                return
            }
            withEnableNotificationGuard(
                values.alert,
                async () => {
                    try {
                        await logsAlertsPartialUpdate(String(values.currentTeamId), props.id, {
                            enabled: !(values.alert!.enabled ?? true),
                        })
                        actions.loadAlert()
                    } catch {
                        lemonToast.error('Failed to update alert')
                    }
                },
                () => actions.setActiveTab('notifications')
            )
        },
        snoozeAlert: async ({ durationMinutes }) => {
            const snoozeUntil = dayjs().add(durationMinutes, 'minute').toISOString()
            try {
                await logsAlertsPartialUpdate(String(values.currentTeamId), props.id, {
                    snooze_until: snoozeUntil,
                })
                lemonToast.success('Alert snoozed')
                actions.loadAlert()
            } catch {
                lemonToast.error('Failed to snooze alert')
            }
        },
        unsnoozeAlert: async () => {
            try {
                await logsAlertsPartialUpdate(String(values.currentTeamId), props.id, { snooze_until: null })
                lemonToast.success('Alert unsnoozed')
                actions.loadAlert()
            } catch {
                lemonToast.error('Failed to unsnooze alert')
            }
        },
        resetAlert: async () => {
            try {
                await logsAlertsResetCreate(String(values.currentTeamId), props.id)
                lemonToast.success('Alert reset — next check will run shortly.')
                actions.loadAlert()
            } catch {
                lemonToast.error('Failed to reset alert')
            }
        },
        deleteAlert: async () => {
            try {
                await logsAlertsDestroy(String(values.currentTeamId), props.id)
                lemonToast.success('Alert deleted')
                actions.loadAlerts()
                router.actions.push(`${urls.logs()}?activeTab=alerts`)
            } catch {
                lemonToast.error('Failed to delete alert')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAlert()
    }),

    urlToAction(({ actions, values }) => ({
        '/logs/alerts/:id': (_, searchParams) => {
            const tab = searchParams.tab as LogsAlertDetailTab | undefined
            const resolved = tab && VALID_TABS.includes(tab) ? tab : DEFAULT_TAB
            if (resolved !== values.activeTab) {
                actions.setActiveTab(resolved)
            }
        },
    })),

    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const params = { ...router.values.searchParams }
            if (values.activeTab === DEFAULT_TAB) {
                delete params.tab
            } else {
                params.tab = values.activeTab
            }
            return [router.values.location.pathname, params, router.values.hashParams, { replace: true }]
        },
    })),
])
