import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { LogMessage } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import {
    logsAlertsCreate,
    logsAlertsPartialUpdate,
    logsAlertsSimulateCreate,
} from 'products/logs/frontend/generated/api'
import {
    LogsAlertConfigurationApi,
    LogsAlertSimulateResponseApi,
    PatchedLogsAlertConfigurationApi,
    ThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertFormLogicType } from './logsAlertFormLogicType'
import { logsAlertingLogic } from './logsAlertingLogic'
import { logsAlertNotificationLogic } from './logsAlertNotificationLogic'

const EMPTY_FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [],
}

export interface LogsAlertFormType {
    name: string
    severityLevels: LogMessage['severity_text'][]
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    thresholdOperator: ThresholdOperatorEnumApi
    thresholdCount: number
    windowMinutes: number
    evaluationPeriods: number
    datapointsToAlarm: number
    cooldownMinutes: number
}

export interface LogsAlertFormLogicProps {
    alert: LogsAlertConfigurationApi | null
}

function extractFilterGroup(alert: LogsAlertConfigurationApi | null): UniversalFiltersGroup {
    const filters = (alert?.filters ?? {}) as Record<string, unknown>
    const stored = filters.filterGroup as { type: string; values: unknown[] } | undefined
    if (stored?.values) {
        const innerGroup = stored.values[0] as UniversalFiltersGroup | undefined
        if (innerGroup?.values) {
            return innerGroup
        }
    }
    return EMPTY_FILTER_GROUP
}

function buildFilters(
    severityLevels: string[],
    serviceNames: string[],
    filterGroup: UniversalFiltersGroup
): Record<string, unknown> {
    const filters: Record<string, unknown> = {}
    if (severityLevels.length > 0) {
        filters.severityLevels = severityLevels
    }
    if (serviceNames.length > 0) {
        filters.serviceNames = serviceNames
    }
    if (filterGroup.values.length > 0) {
        filters.filterGroup = {
            type: FilterLogicalOperator.And,
            values: [filterGroup],
        }
    }
    return filters
}

function hasAnyFilter(severityLevels: string[], serviceNames: string[], filterGroup: UniversalFiltersGroup): boolean {
    return severityLevels.length > 0 || serviceNames.length > 0 || filterGroup.values.length > 0
}

function buildFormDefaults(alert: LogsAlertConfigurationApi | null): LogsAlertFormType {
    return {
        name: alert?.name ?? '',
        severityLevels:
            ((alert?.filters as Record<string, unknown>)?.severityLevels as LogMessage['severity_text'][]) ?? [],
        serviceNames: ((alert?.filters as Record<string, unknown>)?.serviceNames as string[]) ?? [],
        filterGroup: extractFilterGroup(alert),
        thresholdOperator: alert?.threshold_operator ?? ThresholdOperatorEnumApi.Above,
        thresholdCount: alert?.threshold_count ?? 100,
        windowMinutes: alert?.window_minutes ?? 10,
        evaluationPeriods: alert?.evaluation_periods ?? 1,
        datapointsToAlarm: alert?.datapoints_to_alarm ?? 1,
        cooldownMinutes: alert?.cooldown_minutes ?? 0,
    }
}

export const logsAlertFormLogic = kea<logsAlertFormLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsAlerting', 'logsAlertFormLogic']),
    props({} as LogsAlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),

    connect(({ alert }: LogsAlertFormLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            logsAlertNotificationLogic({ alertId: alert?.id }),
            ['pendingNotifications'],
        ],
        actions: [
            logsAlertingLogic,
            ['loadAlerts', 'setEditingAlert', 'setIsCreating'],
            logsAlertNotificationLogic({ alertId: alert?.id }),
            ['createPendingHogFunctions'],
        ],
    })),

    actions({
        simulateAlert: true,
        clearSimulation: true,
        setSimulationDateFrom: (dateFrom: string) => ({ dateFrom }),
        openSimulationPanel: true,
        closeSimulationPanel: true,
    }),

    reducers({
        isSimulationPanelOpen: [
            false,
            {
                openSimulationPanel: () => true,
                closeSimulationPanel: () => false,
            },
        ],
        simulationDateFrom: [
            '-24h' as string,
            {
                setSimulationDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
    }),

    loaders(({ values }) => ({
        simulationResult: [
            null as LogsAlertSimulateResponseApi | null,
            {
                simulateAlert: async (): Promise<LogsAlertSimulateResponseApi | null> => {
                    const form = values.alertForm
                    if (!hasAnyFilter(form.severityLevels, form.serviceNames, form.filterGroup)) {
                        lemonToast.error('At least one filter is required to simulate')
                        return null
                    }
                    const projectId = String(values.currentTeamId)
                    return await logsAlertsSimulateCreate(projectId, {
                        filters: buildFilters(form.severityLevels, form.serviceNames, form.filterGroup),
                        threshold_count: form.thresholdCount,
                        threshold_operator: form.thresholdOperator,
                        window_minutes: form.windowMinutes,
                        evaluation_periods: form.evaluationPeriods,
                        datapoints_to_alarm: form.datapointsToAlarm,
                        cooldown_minutes: form.cooldownMinutes,
                        date_from: values.simulationDateFrom,
                    })
                },
                clearSimulation: () => null,
            },
        ],
    })),

    listeners(({ actions }) => ({
        setAlertFormValue: () => {
            actions.clearSimulation()
        },
        simulateAlertFailure: ({ error }) => {
            lemonToast.error(`Simulation failed: ${error || 'Unknown error'}`)
        },
    })),

    selectors({
        isEditing: [() => [(_, props) => props.alert], (alert: LogsAlertConfigurationApi | null) => alert !== null],
    }),

    afterMount(({ actions, props }) => {
        // Pass values explicitly to reset — kea caches logic instances by key,
        // so defaults from a previous mount may be stale
        actions.resetAlertForm(buildFormDefaults(props.alert))
    }),

    forms(({ props, actions, values }) => ({
        alertForm: {
            // Provides typed shape for kea-forms; afterMount resets with fresh values on every remount
            defaults: buildFormDefaults(props.alert),
            errors: ({ name }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async (form) => {
                if (!hasAnyFilter(form.severityLevels, form.serviceNames, form.filterGroup)) {
                    lemonToast.error('At least one filter is required')
                    throw new Error('At least one filter is required')
                }
                const projectId = String(values.currentTeamId)
                const payload = {
                    name: form.name.trim(),
                    filters: buildFilters(form.severityLevels, form.serviceNames, form.filterGroup),
                    threshold_count: form.thresholdCount,
                    threshold_operator: form.thresholdOperator,
                    window_minutes: form.windowMinutes,
                    evaluation_periods: form.evaluationPeriods,
                    datapoints_to_alarm: form.datapointsToAlarm,
                    cooldown_minutes: form.cooldownMinutes,
                }

                try {
                    let savedAlertId: string
                    if (props.alert) {
                        const patch: PatchedLogsAlertConfigurationApi = { ...payload }
                        await logsAlertsPartialUpdate(projectId, props.alert.id, patch)
                        savedAlertId = props.alert.id
                        lemonToast.success('Alert updated')
                    } else {
                        const created = await logsAlertsCreate(projectId, payload)
                        savedAlertId = created.id
                        lemonToast.success('Alert created')
                    }

                    if (values.pendingNotifications.length > 0) {
                        const notifLogic = logsAlertNotificationLogic({ alertId: props.alert?.id })
                        await notifLogic.asyncActions.createPendingHogFunctions(savedAlertId)
                    }

                    actions.setEditingAlert(null)
                    actions.setIsCreating(false)
                    actions.loadAlerts()
                } catch (e: any) {
                    const message =
                        typeof e?.detail === 'string'
                            ? e.detail
                            : typeof e?.message === 'string'
                              ? e.message
                              : 'Failed to save alert'
                    lemonToast.error(message)
                    throw e
                }
                return form
            },
        },
    })),
])
