import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { evaluationReportLogicType } from './evaluationReportLogicType'
import type {
    EvaluationReport,
    EvaluationReportDeliveryTarget,
    EvaluationReportFrequency,
    EvaluationReportRun,
} from './types'

export interface EvaluationReportLogicProps {
    evaluationId: string
}

export interface PendingReportConfig {
    enabled: boolean
    frequency: EvaluationReportFrequency
    emailValue: string
    slackIntegrationId: number | null
    slackChannelValue: string
}

const DEFAULT_PENDING_CONFIG: PendingReportConfig = {
    enabled: false,
    frequency: 'daily',
    emailValue: '',
    slackIntegrationId: null,
    slackChannelValue: '',
}

export const evaluationReportLogic = kea<evaluationReportLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'evaluations', 'evaluationReportLogic']),
    props({} as EvaluationReportLogicProps),
    key((props) => props.evaluationId),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        // Pending config for new evaluations
        setPendingEnabled: (enabled: boolean) => ({ enabled }),
        setPendingFrequency: (frequency: EvaluationReportFrequency) => ({ frequency }),
        setPendingEmailValue: (emailValue: string) => ({ emailValue }),
        setPendingSlackIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setPendingSlackChannelValue: (channelValue: string) => ({ channelValue }),
        createPendingReport: (evaluationId: string) => ({ evaluationId }),

        // Existing report actions
        selectReportRun: (reportRun: EvaluationReportRun | null) => ({ reportRun }),
    }),

    reducers({
        pendingConfig: [
            DEFAULT_PENDING_CONFIG as PendingReportConfig,
            {
                setPendingEnabled: (state, { enabled }) => ({ ...state, enabled }),
                setPendingFrequency: (state, { frequency }) => ({ ...state, frequency }),
                setPendingEmailValue: (state, { emailValue }) => ({ ...state, emailValue }),
                setPendingSlackIntegrationId: (state, { integrationId }) => ({
                    ...state,
                    slackIntegrationId: integrationId,
                    slackChannelValue: integrationId !== state.slackIntegrationId ? '' : state.slackChannelValue,
                }),
                setPendingSlackChannelValue: (state, { channelValue }) => ({
                    ...state,
                    slackChannelValue: channelValue,
                }),
            },
        ],
        selectedReportRun: [
            null as EvaluationReportRun | null,
            {
                selectReportRun: (_, { reportRun }) => reportRun,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        reports: [
            [] as EvaluationReport[],
            {
                loadReports: async () => {
                    if (props.evaluationId === 'new') {
                        return []
                    }
                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/`
                    )
                    return (response.results || []).filter((r: EvaluationReport) => r.evaluation === props.evaluationId)
                },
                createReport: async (params: {
                    evaluationId: string
                    frequency: EvaluationReportFrequency
                    delivery_targets: EvaluationReportDeliveryTarget[]
                }) => {
                    const report = await api.create(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/`,
                        {
                            evaluation: params.evaluationId,
                            frequency: params.frequency,
                            start_date: new Date().toISOString(),
                            delivery_targets: params.delivery_targets,
                            enabled: true,
                        }
                    )
                    return [...values.reports, report]
                },
                updateReport: async ({ reportId, data }: { reportId: string; data: Partial<EvaluationReport> }) => {
                    const updated = await api.update(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/${reportId}/`,
                        data
                    )
                    return values.reports.map((r) => (r.id === reportId ? updated : r))
                },
                deleteReport: async (reportId: string) => {
                    await api.update(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/${reportId}/`,
                        { deleted: true }
                    )
                    return values.reports.filter((r) => r.id !== reportId)
                },
            },
        ],
        reportRuns: [
            [] as EvaluationReportRun[],
            {
                loadReportRuns: async (reportId: string) => {
                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/${reportId}/runs/`
                    )
                    return response || []
                },
            },
        ],
        generateResult: [
            null as null,
            {
                generateReport: async (reportId: string) => {
                    await api.create(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/${reportId}/generate/`
                    )
                    return null
                },
            },
        ],
    })),

    selectors({
        isNewEvaluation: [(_, p) => [p.evaluationId], (evaluationId: string) => evaluationId === 'new'],
        activeReport: [
            (s) => [s.reports],
            (reports): EvaluationReport | null => {
                return reports.find((r: EvaluationReport) => r.enabled && !r.deleted) || null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createReportSuccess: () => {
            actions.loadReports()
        },
        updateReportSuccess: () => {
            actions.loadReports()
        },
        createPendingReport: ({ evaluationId }) => {
            const { pendingConfig } = values
            if (!pendingConfig.enabled) {
                return
            }
            const targets: EvaluationReportDeliveryTarget[] = []
            if (pendingConfig.emailValue.trim()) {
                targets.push({ type: 'email', value: pendingConfig.emailValue.trim() })
            }
            if (pendingConfig.slackIntegrationId && pendingConfig.slackChannelValue) {
                targets.push({
                    type: 'slack',
                    integration_id: pendingConfig.slackIntegrationId,
                    channel: pendingConfig.slackChannelValue,
                })
            }
            if (targets.length === 0) {
                return
            }
            actions.createReport({
                evaluationId,
                frequency: pendingConfig.frequency,
                delivery_targets: targets,
            })
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.evaluationId !== 'new') {
            actions.loadReports()
        }
    }),
])
