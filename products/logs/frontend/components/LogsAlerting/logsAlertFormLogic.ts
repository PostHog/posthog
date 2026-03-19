import { connect, kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { LogMessage } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { logsAlertsCreate, logsAlertsPartialUpdate } from 'products/logs/frontend/generated/api'
import {
    LogsAlertConfigurationApi,
    PatchedLogsAlertConfigurationApi,
    ThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertFormLogicType } from './logsAlertFormLogicType'
import { logsAlertingLogic } from './logsAlertingLogic'

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

export const logsAlertFormLogic = kea<logsAlertFormLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsAlerting', 'logsAlertFormLogic']),
    props({} as LogsAlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),

    connect({
        values: [teamLogic, ['currentTeamId']],
        actions: [logsAlertingLogic, ['loadAlerts', 'setEditingAlert', 'setIsCreating']],
    }),

    selectors({
        isEditing: [() => [(_, props) => props.alert], (alert: LogsAlertConfigurationApi | null) => alert !== null],
    }),

    forms(({ props, actions, values }) => ({
        alertForm: {
            defaults: {
                name: props.alert?.name ?? '',
                severityLevels: ((props.alert?.filters as Record<string, unknown>)?.severityLevels as string[]) ?? [],
                serviceNames: ((props.alert?.filters as Record<string, unknown>)?.serviceNames as string[]) ?? [],
                filterGroup: extractFilterGroup(props.alert),
                thresholdOperator: props.alert?.threshold_operator ?? ThresholdOperatorEnumApi.Above,
                thresholdCount: props.alert?.threshold_count ?? 100,
                windowMinutes: props.alert?.window_minutes ?? 10,
                evaluationPeriods: props.alert?.evaluation_periods ?? 1,
                datapointsToAlarm: props.alert?.datapoints_to_alarm ?? 1,
                cooldownMinutes: props.alert?.cooldown_minutes ?? 0,
            } as LogsAlertFormType,
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
                    if (props.alert) {
                        const patch: PatchedLogsAlertConfigurationApi = { ...payload }
                        await logsAlertsPartialUpdate(projectId, props.alert.id, patch)
                        lemonToast.success('Alert updated')
                    } else {
                        await logsAlertsCreate(projectId, payload)
                        lemonToast.success('Alert created')
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
