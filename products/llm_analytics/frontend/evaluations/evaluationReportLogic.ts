import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
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

/** Draft state for the report config form — used for both the create-new-evaluation path
 * (keyed as 'new') and the edit-existing-evaluation path (keyed by the real evaluation id). */
export interface ReportConfigDraft {
    enabled: boolean
    frequency: EvaluationReportFrequency
    rrule: string
    startsAt: string | null
    timezoneName: string
    emailValue: string
    slackIntegrationId: number | null
    slackChannelValue: string
    reportPromptGuidance: string
    triggerThreshold: number
    cooldownHours: number
}

export const TRIGGER_THRESHOLD_DEFAULT = 100
export const COOLDOWN_HOURS_DEFAULT = 1
export const COOLDOWN_HOURS_MIN = 1
export const COOLDOWN_HOURS_MAX = 24
export const DEFAULT_RRULE = 'FREQ=DAILY'
export const DEFAULT_TIMEZONE = 'UTC'

const DEFAULT_CONFIG_DRAFT: ReportConfigDraft = {
    enabled: true,
    frequency: 'every_n',
    rrule: '',
    startsAt: null,
    timezoneName: DEFAULT_TIMEZONE,
    emailValue: '',
    slackIntegrationId: null,
    slackChannelValue: '',
    reportPromptGuidance: '',
    triggerThreshold: TRIGGER_THRESHOLD_DEFAULT,
    cooldownHours: COOLDOWN_HOURS_DEFAULT,
}

function draftFromReport(report: EvaluationReport): ReportConfigDraft {
    const emailTarget = report.delivery_targets.find((t) => t.type === 'email')
    const slackTarget = report.delivery_targets.find((t) => t.type === 'slack')
    // Normalise here so the dirty check (which compares against draft.emailValue
    // that buildDeliveryTargets later trims) doesn't fire a false positive when
    // the stored value is surrounded by whitespace.
    return {
        enabled: true,
        frequency: report.frequency,
        rrule: report.rrule ?? '',
        startsAt: report.starts_at ?? null,
        timezoneName: report.timezone_name ?? DEFAULT_TIMEZONE,
        emailValue: (emailTarget?.value ?? '').trim(),
        slackIntegrationId: slackTarget?.integration_id ?? null,
        slackChannelValue: slackTarget?.channel ?? '',
        reportPromptGuidance: report.report_prompt_guidance ?? '',
        triggerThreshold: report.trigger_threshold ?? TRIGGER_THRESHOLD_DEFAULT,
        cooldownHours: Math.max(1, Math.round((report.cooldown_minutes ?? COOLDOWN_HOURS_DEFAULT * 60) / 60)),
    }
}

export function buildDeliveryTargets(draft: ReportConfigDraft): EvaluationReportDeliveryTarget[] {
    const targets: EvaluationReportDeliveryTarget[] = []
    const email = draft.emailValue.trim()
    if (email.length > 0) {
        targets.push({ type: 'email', value: email })
    }
    if (draft.slackIntegrationId !== null && draft.slackChannelValue.length > 0) {
        targets.push({
            type: 'slack',
            integration_id: draft.slackIntegrationId,
            channel: draft.slackChannelValue,
        })
    }
    return targets
}

export const evaluationReportLogic = kea<evaluationReportLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'evaluations', 'evaluationReportLogic']),
    props({} as EvaluationReportLogicProps),
    key((props) => props.evaluationId),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setDraftEnabled: (enabled: boolean) => ({ enabled }),
        setDraftFrequency: (frequency: EvaluationReportFrequency) => ({ frequency }),
        setDraftRrule: (rrule: string) => ({ rrule }),
        setDraftStartsAt: (startsAt: string | null) => ({ startsAt }),
        setDraftTimezoneName: (timezoneName: string) => ({ timezoneName }),
        setDraftEmailValue: (emailValue: string) => ({ emailValue }),
        setDraftSlackIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setDraftSlackChannelValue: (channelValue: string) => ({ channelValue }),
        setDraftReportPromptGuidance: (reportPromptGuidance: string) => ({ reportPromptGuidance }),
        setDraftTriggerThreshold: (triggerThreshold: number) => ({ triggerThreshold }),
        setDraftCooldownHours: (cooldownHours: number) => ({ cooldownHours }),
        seedDraftFromReport: (report: EvaluationReport) => ({ report }),
        resetDraft: true,

        /** Save the current draft against the active report — creates if none exists, updates otherwise. */
        saveDraft: true,

        selectReportRun: (reportRun: EvaluationReportRun | null) => ({ reportRun }),
    }),

    reducers({
        configDraft: [
            DEFAULT_CONFIG_DRAFT as ReportConfigDraft,
            {
                setDraftEnabled: (state, { enabled }) => ({ ...state, enabled }),
                setDraftFrequency: (state, { frequency }) => {
                    // Seed a default rrule when switching into scheduled mode for the first time so
                    // the Save button can commit without forcing the user to fill the field manually.
                    const rrule = frequency === 'scheduled' && !state.rrule ? DEFAULT_RRULE : state.rrule
                    const startsAt =
                        frequency === 'scheduled' && !state.startsAt ? new Date().toISOString() : state.startsAt
                    return { ...state, frequency, rrule, startsAt }
                },
                setDraftRrule: (state, { rrule }) => ({ ...state, rrule }),
                setDraftStartsAt: (state, { startsAt }) => ({ ...state, startsAt }),
                setDraftTimezoneName: (state, { timezoneName }) => ({ ...state, timezoneName }),
                setDraftEmailValue: (state, { emailValue }) => ({ ...state, emailValue }),
                setDraftSlackIntegrationId: (state, { integrationId }) => ({
                    ...state,
                    slackIntegrationId: integrationId,
                    // Clear channel when switching Slack workspaces so we don't send a
                    // channel id from a different workspace.
                    slackChannelValue: integrationId !== state.slackIntegrationId ? '' : state.slackChannelValue,
                }),
                setDraftSlackChannelValue: (state, { channelValue }) => ({
                    ...state,
                    slackChannelValue: channelValue,
                }),
                setDraftReportPromptGuidance: (state, { reportPromptGuidance }) => ({
                    ...state,
                    reportPromptGuidance,
                }),
                setDraftTriggerThreshold: (state, { triggerThreshold }) => ({
                    ...state,
                    triggerThreshold,
                }),
                setDraftCooldownHours: (state, { cooldownHours }) => ({
                    ...state,
                    cooldownHours,
                }),
                seedDraftFromReport: (_, { report }) => draftFromReport(report),
                resetDraft: () => DEFAULT_CONFIG_DRAFT,
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
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/?evaluation=${props.evaluationId}`
                    )
                    return response.results || []
                },
                createReport: async (params: {
                    evaluationId: string
                    frequency: EvaluationReportFrequency
                    rrule?: string
                    starts_at?: string | null
                    timezone_name?: string
                    delivery_targets: EvaluationReportDeliveryTarget[]
                    report_prompt_guidance?: string
                    trigger_threshold?: number | null
                    cooldown_minutes?: number | null
                }) => {
                    const body: Record<string, unknown> = {
                        evaluation: params.evaluationId,
                        frequency: params.frequency,
                        delivery_targets: params.delivery_targets,
                        report_prompt_guidance: params.report_prompt_guidance ?? '',
                        enabled: true,
                    }
                    if (params.frequency === 'scheduled') {
                        body.rrule = params.rrule ?? ''
                        body.starts_at = params.starts_at ?? null
                        body.timezone_name = params.timezone_name ?? DEFAULT_TIMEZONE
                    }
                    if (params.frequency === 'every_n' && params.trigger_threshold != null) {
                        body.trigger_threshold = params.trigger_threshold
                    }
                    if (params.frequency === 'every_n' && params.cooldown_minutes != null) {
                        body.cooldown_minutes = params.cooldown_minutes
                    }
                    const report = await api.create(
                        `api/environments/${values.currentTeamId}/llm_analytics/evaluation_reports/`,
                        body
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
                    // The runs endpoint is paginated (DRF envelope); unwrap results so the
                    // reducer gets an array rather than the {count, next, previous, results} object.
                    return response?.results || []
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
        isConfigDirty: [
            (s) => [s.activeReport, s.configDraft],
            (activeReport, draft): boolean => {
                if (!activeReport) {
                    // No report yet: draft is "dirty" if it has any savable content.
                    return buildDeliveryTargets(draft).length > 0 || draft.reportPromptGuidance.trim().length > 0
                }
                const baseline = draftFromReport(activeReport)
                const scheduleDirty =
                    draft.frequency === 'scheduled' &&
                    (baseline.rrule !== draft.rrule ||
                        baseline.startsAt !== draft.startsAt ||
                        baseline.timezoneName !== draft.timezoneName)
                return (
                    baseline.frequency !== draft.frequency ||
                    baseline.emailValue !== draft.emailValue.trim() ||
                    baseline.slackIntegrationId !== draft.slackIntegrationId ||
                    baseline.slackChannelValue !== draft.slackChannelValue ||
                    baseline.reportPromptGuidance !== draft.reportPromptGuidance ||
                    (draft.frequency === 'every_n' && baseline.triggerThreshold !== draft.triggerThreshold) ||
                    (draft.frequency === 'every_n' && baseline.cooldownHours !== draft.cooldownHours) ||
                    scheduleDirty
                )
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadReportsSuccess: ({ reports }) => {
            // Auto-load the run history for the active report so the Reports tab knows
            // whether to render itself and can show data immediately.
            const active = reports.find((r: EvaluationReport) => r.enabled && !r.deleted)
            if (active) {
                actions.loadReportRuns(active.id)
                // Seed the draft so the config form reflects the saved report instead of defaults.
                actions.seedDraftFromReport(active)
            }
        },
        generateReportSuccess: () => {
            lemonToast.success('Report is being generated and will be delivered to your configured targets shortly.')
        },
        generateReportFailure: () => {
            lemonToast.error('Failed to trigger report generation. Please try again.')
        },
        createReportSuccess: () => {
            actions.loadReports()
        },
        updateReportSuccess: () => {
            actions.loadReports()
        },
        saveDraft: () => {
            const { configDraft, activeReport } = values
            const targets = buildDeliveryTargets(configDraft)
            if (activeReport) {
                const data: Record<string, unknown> = {
                    frequency: configDraft.frequency,
                    delivery_targets: targets,
                    report_prompt_guidance: configDraft.reportPromptGuidance,
                }
                if (configDraft.frequency === 'scheduled') {
                    data.rrule = configDraft.rrule
                    data.starts_at = configDraft.startsAt
                    data.timezone_name = configDraft.timezoneName
                }
                if (configDraft.frequency === 'every_n') {
                    data.trigger_threshold = configDraft.triggerThreshold
                    // Only write cooldown_minutes back when the user changed it — the draft rounds
                    // minutes to hours for display, so unconditionally writing (hours * 60) would
                    // silently clobber sub-hour values set via the API (e.g. 89 min → 60 min).
                    const seededCooldownHours = Math.max(1, Math.round((activeReport.cooldown_minutes ?? 60) / 60))
                    if (configDraft.cooldownHours !== seededCooldownHours) {
                        data.cooldown_minutes = configDraft.cooldownHours * 60
                    }
                }
                actions.updateReport({ reportId: activeReport.id, data })
            } else {
                actions.createReport({
                    evaluationId: props.evaluationId,
                    frequency: configDraft.frequency,
                    rrule: configDraft.rrule,
                    starts_at: configDraft.startsAt,
                    timezone_name: configDraft.timezoneName,
                    delivery_targets: targets,
                    report_prompt_guidance: configDraft.reportPromptGuidance,
                    trigger_threshold: configDraft.frequency === 'every_n' ? configDraft.triggerThreshold : null,
                    cooldown_minutes: configDraft.frequency === 'every_n' ? configDraft.cooldownHours * 60 : null,
                })
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.evaluationId !== 'new') {
            actions.loadReports()
        }
    }),
])
