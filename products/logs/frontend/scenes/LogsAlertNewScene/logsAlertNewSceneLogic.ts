import { actions, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    logsAlertFormLogic,
    LogsAlertFormType,
} from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { buildAlertFilters, hasAnyFilter } from 'products/logs/frontend/components/LogsAlerting/logsAlertUtils'
import { logsAlertsCreate } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsAlertNewSceneLogicType } from './logsAlertNewSceneLogicType'

export const logsAlertNewSceneLogic = kea<logsAlertNewSceneLogicType>([
    path(['products', 'logs', 'frontend', 'scenes', 'LogsAlertNewScene', 'logsAlertNewSceneLogic']),

    connect({
        values: [teamLogic, ['currentTeamId'], logsAlertFormLogic({ alert: null }), ['alertForm']],
    }),

    actions({
        createDraft: true,
    }),

    loaders(({ values }) => ({
        createdAlert: [
            null as LogsAlertConfigurationApi | null,
            {
                createDraft: async () => {
                    const form = values.alertForm
                    if (!form.name?.trim()) {
                        lemonToast.error('Name is required')
                        return null
                    }
                    if (!hasAnyFilter(form.severityLevels, form.serviceNames, form.filterGroup)) {
                        lemonToast.error('At least one filter is required')
                        return null
                    }
                    const projectId = String(values.currentTeamId)
                    try {
                        const created = await logsAlertsCreate(projectId, {
                            name: form.name.trim(),
                            filters: buildAlertFilters(form.severityLevels, form.serviceNames, form.filterGroup),
                            threshold_count: form.thresholdCount,
                            threshold_operator: form.thresholdOperator,
                            window_minutes: form.windowMinutes,
                            evaluation_periods: form.evaluationPeriods,
                            datapoints_to_alarm: form.datapointsToAlarm,
                            cooldown_minutes: form.cooldownMinutes,
                            enabled: false,
                        })
                        return created
                    } catch (e: any) {
                        lemonToast.error(e?.detail ?? e?.message ?? 'Failed to create alert')
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                { key: Scene.Logs, name: 'Logs', path: `${urls.logs()}?activeTab=alerts`, iconType: 'logs' },
                { key: Scene.LogsAlertNew, name: 'New alert', iconType: 'logs' },
            ],
        ],

        canCreateDraft: [
            (s) => [s.alertForm],
            (form: LogsAlertFormType): boolean =>
                !!form.name?.trim() && hasAnyFilter(form.severityLevels, form.serviceNames, form.filterGroup),
        ],
    }),

    listeners(() => ({
        createDraftSuccess: ({ createdAlert }) => {
            if (createdAlert) {
                lemonToast.success('Draft alert created — enable it once notifications are configured.')
                router.actions.push(urls.logsAlertDetail(createdAlert.id))
            }
        },
    })),
])
