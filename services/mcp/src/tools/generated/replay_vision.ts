// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/replay_vision/api'
import { withUiApp } from '@/resources/ui-apps'
import { castBooleanToString } from '@/tools/cast-helpers'
import { withPostHogUrl, withAgentNote, type WithPostHogUrl, type WithAgentNote } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisionQuotaSpendSeriesGetSchema = () => z.object({})

const visionQuotaSpendSeriesGet = (): ToolBase<
    ReturnType<typeof VisionQuotaSpendSeriesGetSchema>,
    Schemas.VisionSpendSeries
> => ({
    name: 'vision-quota-spend-series-get',
    schema: VisionQuotaSpendSeriesGetSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof VisionQuotaSpendSeriesGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionSpendSeries>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/quota/spend_series/`,
        })
        return result
    },
})

const VisionAlertsCreateSchema = () => {
    const VisionAlertsCreateBody = orvalSchemas.VisionAlertsCreateBody()
    return VisionAlertsCreateBody
}

const visionAlertsCreate = (): ToolBase<
    ReturnType<typeof VisionAlertsCreateSchema>,
    Schemas.VisionAlertConfiguration
> => ({
    name: 'vision-alerts-create',
    schema: VisionAlertsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.scanner_id !== undefined) {
            body['scanner_id'] = params.scanner_id
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.selection !== undefined) {
            body['selection'] = params.selection
        }
        if (params.metric !== undefined) {
            body['metric'] = params.metric
        }
        if (params.direction !== undefined) {
            body['direction'] = params.direction
        }
        if (params.threshold !== undefined) {
            body['threshold'] = params.threshold
        }
        if (params.window_days !== undefined) {
            body['window_days'] = params.window_days
        }
        if (params.check_interval_minutes !== undefined) {
            body['check_interval_minutes'] = params.check_interval_minutes
        }
        if (params.evaluation_periods !== undefined) {
            body['evaluation_periods'] = params.evaluation_periods
        }
        if (params.datapoints_to_alarm !== undefined) {
            body['datapoints_to_alarm'] = params.datapoints_to_alarm
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.schedule_restriction !== undefined) {
            body['schedule_restriction'] = params.schedule_restriction
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        const result = await context.api.request<Schemas.VisionAlertConfiguration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/`,
            body,
        })
        return result
    },
})

const VisionAlertsDestinationsCreateSchema = () => {
    const VisionAlertsDestinationsCreateBody = orvalSchemas.VisionAlertsDestinationsCreateBody()
    const VisionAlertsDestinationsCreateParams = orvalSchemas.VisionAlertsDestinationsCreateParams()
    return VisionAlertsDestinationsCreateParams.omit({ project_id: true }).extend(
        VisionAlertsDestinationsCreateBody.shape
    )
}

const visionAlertsDestinationsCreate = (): ToolBase<
    ReturnType<typeof VisionAlertsDestinationsCreateSchema>,
    Schemas.VisionAlertDestinationResponse
> => ({
    name: 'vision-alerts-destinations-create',
    schema: VisionAlertsDestinationsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsDestinationsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.slack_workspace_id !== undefined) {
            body['slack_workspace_id'] = params.slack_workspace_id
        }
        if (params.slack_channel_id !== undefined) {
            body['slack_channel_id'] = params.slack_channel_id
        }
        if (params.slack_channel_name !== undefined) {
            body['slack_channel_name'] = params.slack_channel_name
        }
        if (params.webhook_url !== undefined) {
            body['webhook_url'] = params.webhook_url
        }
        const result = await context.api.request<Schemas.VisionAlertDestinationResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/destinations/`,
            body,
        })
        return result
    },
})

const VisionAlertsDestinationsDeleteSchema = () => {
    const VisionAlertsDestinationsDeleteCreateBody = orvalSchemas.VisionAlertsDestinationsDeleteCreateBody()
    const VisionAlertsDestinationsDeleteCreateParams = orvalSchemas.VisionAlertsDestinationsDeleteCreateParams()
    return VisionAlertsDestinationsDeleteCreateParams.omit({ project_id: true }).extend(
        VisionAlertsDestinationsDeleteCreateBody.shape
    )
}

const visionAlertsDestinationsDelete = (): ToolBase<
    ReturnType<typeof VisionAlertsDestinationsDeleteSchema>,
    unknown
> => ({
    name: 'vision-alerts-destinations-delete',
    schema: VisionAlertsDestinationsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsDestinationsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.hog_function_ids !== undefined) {
            body['hog_function_ids'] = params.hog_function_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/destinations/delete/`,
            body,
        })
        return result
    },
})

const VisionAlertsDeleteSchema = () => {
    const VisionAlertsDestroyParams = orvalSchemas.VisionAlertsDestroyParams()
    return VisionAlertsDestroyParams.omit({ project_id: true })
}

const visionAlertsDelete = (): ToolBase<ReturnType<typeof VisionAlertsDeleteSchema>, unknown> => ({
    name: 'vision-alerts-delete',
    schema: VisionAlertsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionAlertsEventsListSchema = () => {
    const VisionAlertsEventsListParams = orvalSchemas.VisionAlertsEventsListParams()
    const VisionAlertsEventsListQueryParams = orvalSchemas.VisionAlertsEventsListQueryParams()
    return VisionAlertsEventsListParams.omit({ project_id: true }).extend(VisionAlertsEventsListQueryParams.shape)
}

const visionAlertsEventsList = (): ToolBase<
    ReturnType<typeof VisionAlertsEventsListSchema>,
    WithPostHogUrl<Schemas.PaginatedVisionAlertEventList>
> => ({
    name: 'vision-alerts-events-list',
    schema: VisionAlertsEventsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsEventsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedVisionAlertEventList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/events/`,
            query: {
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionAlertsListSchema = () => {
    const VisionAlertsListQueryParams = orvalSchemas.VisionAlertsListQueryParams()
    return VisionAlertsListQueryParams
}

const visionAlertsList = (): ToolBase<
    ReturnType<typeof VisionAlertsListSchema>,
    WithPostHogUrl<Schemas.PaginatedVisionAlertConfigurationList>
> => ({
    name: 'vision-alerts-list',
    schema: VisionAlertsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedVisionAlertConfigurationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                scanner_id: params.scanner_id,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionAlertsPartialUpdateSchema = () => {
    const VisionAlertsPartialUpdateBody = orvalSchemas.VisionAlertsPartialUpdateBody()
    const VisionAlertsPartialUpdateParams = orvalSchemas.VisionAlertsPartialUpdateParams()
    return VisionAlertsPartialUpdateParams.omit({ project_id: true }).extend(VisionAlertsPartialUpdateBody.shape)
}

const visionAlertsPartialUpdate = (): ToolBase<
    ReturnType<typeof VisionAlertsPartialUpdateSchema>,
    Schemas.VisionAlertConfiguration
> => ({
    name: 'vision-alerts-partial-update',
    schema: VisionAlertsPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.scanner_id !== undefined) {
            body['scanner_id'] = params.scanner_id
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.selection !== undefined) {
            body['selection'] = params.selection
        }
        if (params.metric !== undefined) {
            body['metric'] = params.metric
        }
        if (params.direction !== undefined) {
            body['direction'] = params.direction
        }
        if (params.threshold !== undefined) {
            body['threshold'] = params.threshold
        }
        if (params.window_days !== undefined) {
            body['window_days'] = params.window_days
        }
        if (params.check_interval_minutes !== undefined) {
            body['check_interval_minutes'] = params.check_interval_minutes
        }
        if (params.evaluation_periods !== undefined) {
            body['evaluation_periods'] = params.evaluation_periods
        }
        if (params.datapoints_to_alarm !== undefined) {
            body['datapoints_to_alarm'] = params.datapoints_to_alarm
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.schedule_restriction !== undefined) {
            body['schedule_restriction'] = params.schedule_restriction
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        const result = await context.api.request<Schemas.VisionAlertConfiguration>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const VisionAlertsResetSchema = () => {
    const VisionAlertsResetCreateParams = orvalSchemas.VisionAlertsResetCreateParams()
    return VisionAlertsResetCreateParams.omit({ project_id: true })
}

const visionAlertsReset = (): ToolBase<
    ReturnType<typeof VisionAlertsResetSchema>,
    Schemas.VisionAlertConfiguration
> => ({
    name: 'vision-alerts-reset',
    schema: VisionAlertsResetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsResetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionAlertConfiguration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/reset/`,
        })
        return result
    },
})

const VisionAlertsGetSchema = () => {
    const VisionAlertsRetrieveParams = orvalSchemas.VisionAlertsRetrieveParams()
    return VisionAlertsRetrieveParams.omit({ project_id: true })
}

const visionAlertsGet = (): ToolBase<ReturnType<typeof VisionAlertsGetSchema>, Schemas.VisionAlertConfiguration> => ({
    name: 'vision-alerts-get',
    schema: VisionAlertsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionAlertsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionAlertConfiguration>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/alerts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionObservationsCreateTaskSchema = () => {
    const VisionObservationsCreateTaskCreateParams = orvalSchemas.VisionObservationsCreateTaskCreateParams()
    return VisionObservationsCreateTaskCreateParams.omit({ project_id: true })
}

const visionObservationsCreateTask = (): ToolBase<
    ReturnType<typeof VisionObservationsCreateTaskSchema>,
    Schemas.CreateTaskFromObservationResponse
> => ({
    name: 'vision-observations-create-task',
    schema: VisionObservationsCreateTaskSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsCreateTaskSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CreateTaskFromObservationResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/create_task/`,
        })
        return result
    },
})

const VisionObservationsLabelCreateSchema = () => {
    const VisionObservationsLabelCreateBody = orvalSchemas.VisionObservationsLabelCreateBody()
    const VisionObservationsLabelCreateParams = orvalSchemas.VisionObservationsLabelCreateParams()
    return VisionObservationsLabelCreateParams.omit({ project_id: true }).extend(
        VisionObservationsLabelCreateBody.shape
    )
}

const visionObservationsLabelCreate = (): ToolBase<
    ReturnType<typeof VisionObservationsLabelCreateSchema>,
    Schemas.ReplayObservationLabel
> => ({
    name: 'vision-observations-label-create',
    schema: VisionObservationsLabelCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsLabelCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.is_correct !== undefined) {
            body['is_correct'] = params.is_correct
        }
        if (params.feedback !== undefined) {
            body['feedback'] = params.feedback
        }
        const result = await context.api.request<Schemas.ReplayObservationLabel>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/label/`,
            body,
        })
        return result
    },
})

const VisionObservationsLabelDestroySchema = () => {
    const VisionObservationsLabelDestroyParams = orvalSchemas.VisionObservationsLabelDestroyParams()
    return VisionObservationsLabelDestroyParams.omit({ project_id: true })
}

const visionObservationsLabelDestroy = (): ToolBase<
    ReturnType<typeof VisionObservationsLabelDestroySchema>,
    unknown
> => ({
    name: 'vision-observations-label-destroy',
    schema: VisionObservationsLabelDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsLabelDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/label/`,
        })
        return result
    },
})

const VisionObservationsListSchema = () => {
    const VisionObservationsListQueryParams = orvalSchemas.VisionObservationsListQueryParams()
    return VisionObservationsListQueryParams
}

const visionObservationsList = (): ToolBase<
    ReturnType<typeof VisionObservationsListSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.PaginatedReplayObservationList>>
> =>
    withUiApp('vision-observation-list', {
        name: 'vision-observations-list',
        schema: VisionObservationsListSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsListSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedReplayObservationList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                    order_by: params.order_by,
                    session_id: params.session_id,
                },
            })
            return withAgentNote(
                await withPostHogUrl(
                    context,
                    {
                        ...result,
                        results: await Promise.all(
                            (result.results ?? []).map((item) =>
                                withPostHogUrl(context, item, `/replay/${item.session_id}`)
                            )
                        ),
                    },
                    '/replay'
                ),
                "Each observation's `_posthogUrl` opens the recording it analysed. `scanner_result.model_output.reasoning_segments` interleaves prose with `chip` segments, and a chip's `timestamp_ms` is the recording-relative offset of the moment being cited — append `?t=<seconds>` (`timestamp_ms` / 1000, rounded down) to that URL to seek straight to it. When you report a finding to someone, deep-link the one or two moments it turns on rather than only describing them.\n"
            )
        },
    })

const VisionObservationsRetrieveSchema = () => {
    const VisionObservationsRetrieveParams = orvalSchemas.VisionObservationsRetrieveParams()
    const VisionObservationsRetrieveQueryParams = orvalSchemas.VisionObservationsRetrieveQueryParams()
    return VisionObservationsRetrieveParams.omit({ project_id: true }).extend(
        VisionObservationsRetrieveQueryParams.shape
    )
}

const visionObservationsRetrieve = (): ToolBase<
    ReturnType<typeof VisionObservationsRetrieveSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.ReplayObservation>>
> => ({
    name: 'vision-observations-retrieve',
    schema: VisionObservationsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayObservation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/`,
            query: {
                backfill_id: params.backfill_id,
                date_from: params.date_from,
                date_to: params.date_to,
                labeled: params.labeled,
                max_score: params.max_score,
                min_score: params.min_score,
                order_by: params.order_by,
                recording_subject: params.recording_subject,
                session_id: params.session_id,
                status: params.status,
                tags: params.tags,
                triggered_by: params.triggered_by,
                verdict: params.verdict,
            },
        })
        return withAgentNote(
            await withPostHogUrl(context, result, `/replay/${result.session_id}`),
            "`_posthogUrl` opens the recording this observation analysed. `scanner_result.model_output.reasoning_segments` interleaves prose with `chip` segments, and a chip's `timestamp_ms` is the recording-relative offset of the moment being cited — append `?t=<seconds>` (`timestamp_ms` / 1000, rounded down) to that URL to seek straight to it. When you report a finding to someone, deep-link the one or two moments it turns on rather than only describing them.\n"
        )
    },
})

const VisionObservationsRetrySchema = () => {
    const VisionObservationsRetryCreateParams = orvalSchemas.VisionObservationsRetryCreateParams()
    return VisionObservationsRetryCreateParams.omit({ project_id: true })
}

const visionObservationsRetry = (): ToolBase<ReturnType<typeof VisionObservationsRetrySchema>, unknown> => ({
    name: 'vision-observations-retry',
    schema: VisionObservationsRetrySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsRetrySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/retry/`,
        })
        return result
    },
})

const VisionObservationsSearchSchema = () => {
    const VisionObservationsSearchRetrieveQueryParams = orvalSchemas.VisionObservationsSearchRetrieveQueryParams()
    return VisionObservationsSearchRetrieveQueryParams
}

const visionObservationsSearch = (): ToolBase<
    ReturnType<typeof VisionObservationsSearchSchema>,
    Schemas.ObservationSearchResponse
> => ({
    name: 'vision-observations-search',
    schema: VisionObservationsSearchSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionObservationsSearchSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ObservationSearchResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/search/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                max_score: params.max_score,
                min_score: params.min_score,
                q: params.q,
                scanner_id: params.scanner_id,
                tags: params.tags,
                verdict: params.verdict,
            },
        })
        return result
    },
})

const VisionObservationsSignalReportsListSchema = () => {
    const VisionObservationsSignalReportsListParams = orvalSchemas.VisionObservationsSignalReportsListParams()
    return VisionObservationsSignalReportsListParams.omit({ project_id: true })
}

const visionObservationsSignalReportsList = (): ToolBase<
    ReturnType<typeof VisionObservationsSignalReportsListSchema>,
    Schemas.ObservationSignalReport[]
> => ({
    name: 'vision-observations-signal-reports-list',
    schema: VisionObservationsSignalReportsListSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof VisionObservationsSignalReportsListSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ObservationSignalReport[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/signal_reports/`,
        })
        return result
    },
})

const VisionQuotaRetrieveSchema = () => z.object({})

const visionQuotaRetrieve = (): ToolBase<ReturnType<typeof VisionQuotaRetrieveSchema>, Schemas.VisionQuota> => ({
    name: 'vision-quota-retrieve',
    schema: VisionQuotaRetrieveSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof VisionQuotaRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionQuota>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/quota/`,
        })
        return result
    },
})

const VisionScannersAffectedCohortCreateSchema = () => {
    const VisionScannersAffectedCohortCreateBody = orvalSchemas.VisionScannersAffectedCohortCreateBody()
    const VisionScannersAffectedCohortCreateParams = orvalSchemas.VisionScannersAffectedCohortCreateParams()
    return VisionScannersAffectedCohortCreateParams.omit({ project_id: true }).extend(
        VisionScannersAffectedCohortCreateBody.shape
    )
}

const visionScannersAffectedCohortCreate = (): ToolBase<
    ReturnType<typeof VisionScannersAffectedCohortCreateSchema>,
    Schemas.AffectedCohortResponse
> => ({
    name: 'vision-scanners-affected-cohort-create',
    schema: VisionScannersAffectedCohortCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersAffectedCohortCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.window_days !== undefined) {
            body['window_days'] = params.window_days
        }
        if (params.tag !== undefined) {
            body['tag'] = params.tag
        }
        if (params.min_score !== undefined) {
            body['min_score'] = params.min_score
        }
        if (params.max_score !== undefined) {
            body['max_score'] = params.max_score
        }
        const result = await context.api.request<Schemas.AffectedCohortResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/affected_cohort/`,
            body,
        })
        return result
    },
})

const VisionScannersBackfillsCancelSchema = () => {
    const VisionScannersBackfillsCancelCreateBody = orvalSchemas.VisionScannersBackfillsCancelCreateBody()
    const VisionScannersBackfillsCancelCreateParams = orvalSchemas.VisionScannersBackfillsCancelCreateParams()
    return VisionScannersBackfillsCancelCreateParams.omit({ project_id: true }).extend(
        VisionScannersBackfillsCancelCreateBody.shape
    )
}

const visionScannersBackfillsCancel = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsCancelSchema>,
    Schemas.ReplayScannerBackfill
> => ({
    name: 'vision-scanners-backfills-cancel',
    schema: VisionScannersBackfillsCancelSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsCancelSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerBackfill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/${encodeURIComponent(String(params.id))}/cancel/`,
        })
        return result
    },
})

const VisionScannersBackfillsCreateSchema = () => {
    const VisionScannersBackfillsCreateBody = orvalSchemas.VisionScannersBackfillsCreateBody()
    const VisionScannersBackfillsCreateParams = orvalSchemas.VisionScannersBackfillsCreateParams()
    return VisionScannersBackfillsCreateParams.omit({ project_id: true }).extend(
        VisionScannersBackfillsCreateBody.shape
    )
}

const visionScannersBackfillsCreate = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsCreateSchema>,
    Schemas.ReplayScannerBackfill
> => ({
    name: 'vision-scanners-backfills-create',
    schema: VisionScannersBackfillsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.window_start !== undefined) {
            body['window_start'] = params.window_start
        }
        if (params.window_end !== undefined) {
            body['window_end'] = params.window_end
        }
        const result = await context.api.request<Schemas.ReplayScannerBackfill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/`,
            body,
        })
        return result
    },
})

const VisionScannersBackfillsEstimateSchema = () => {
    const VisionScannersBackfillsEstimateCreateBody = orvalSchemas.VisionScannersBackfillsEstimateCreateBody()
    const VisionScannersBackfillsEstimateCreateParams = orvalSchemas.VisionScannersBackfillsEstimateCreateParams()
    return VisionScannersBackfillsEstimateCreateParams.omit({ project_id: true }).extend(
        VisionScannersBackfillsEstimateCreateBody.shape
    )
}

const visionScannersBackfillsEstimate = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsEstimateSchema>,
    Schemas.BackfillEstimateResponse
> => ({
    name: 'vision-scanners-backfills-estimate',
    schema: VisionScannersBackfillsEstimateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsEstimateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.window_start !== undefined) {
            body['window_start'] = params.window_start
        }
        if (params.window_end !== undefined) {
            body['window_end'] = params.window_end
        }
        const result = await context.api.request<Schemas.BackfillEstimateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/estimate/`,
            body,
        })
        return result
    },
})

const VisionScannersBackfillsListSchema = () => {
    const VisionScannersBackfillsListParams = orvalSchemas.VisionScannersBackfillsListParams()
    const VisionScannersBackfillsListQueryParams = orvalSchemas.VisionScannersBackfillsListQueryParams()
    return VisionScannersBackfillsListParams.omit({ project_id: true }).extend(
        VisionScannersBackfillsListQueryParams.shape
    )
}

const visionScannersBackfillsList = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsListSchema>,
    WithPostHogUrl<Schemas.PaginatedReplayScannerBackfillList>
> => ({
    name: 'vision-scanners-backfills-list',
    schema: VisionScannersBackfillsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReplayScannerBackfillList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionScannersBackfillsResumeSchema = () => {
    const VisionScannersBackfillsResumeCreateBody = orvalSchemas.VisionScannersBackfillsResumeCreateBody()
    const VisionScannersBackfillsResumeCreateParams = orvalSchemas.VisionScannersBackfillsResumeCreateParams()
    return VisionScannersBackfillsResumeCreateParams.omit({ project_id: true }).extend(
        VisionScannersBackfillsResumeCreateBody.shape
    )
}

const visionScannersBackfillsResume = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsResumeSchema>,
    Schemas.ReplayScannerBackfill
> => ({
    name: 'vision-scanners-backfills-resume',
    schema: VisionScannersBackfillsResumeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsResumeSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerBackfill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/${encodeURIComponent(String(params.id))}/resume/`,
        })
        return result
    },
})

const VisionScannersBackfillsGetSchema = () => {
    const VisionScannersBackfillsRetrieveParams = orvalSchemas.VisionScannersBackfillsRetrieveParams()
    return VisionScannersBackfillsRetrieveParams.omit({ project_id: true })
}

const visionScannersBackfillsGet = (): ToolBase<
    ReturnType<typeof VisionScannersBackfillsGetSchema>,
    Schemas.ReplayScannerBackfill
> => ({
    name: 'vision-scanners-backfills-get',
    schema: VisionScannersBackfillsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersBackfillsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerBackfill>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/backfills/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersScanSessionsSchema = () => {
    const VisionScannersBulkObserveCreateBody = orvalSchemas.VisionScannersBulkObserveCreateBody()
    const VisionScannersBulkObserveCreateParams = orvalSchemas.VisionScannersBulkObserveCreateParams()
    return VisionScannersBulkObserveCreateParams.omit({ project_id: true }).extend(
        VisionScannersBulkObserveCreateBody.shape
    )
}

const visionScannersScanSessions = (): ToolBase<ReturnType<typeof VisionScannersScanSessionsSchema>, unknown> => ({
    name: 'vision-scanners-scan-sessions',
    schema: VisionScannersScanSessionsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersScanSessionsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.session_ids !== undefined) {
            body['session_ids'] = params.session_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/bulk_observe/`,
            body,
        })
        return result
    },
})

const VisionScannersCreateSchema = () => {
    const VisionScannersCreateBody = orvalSchemas.VisionScannersCreateBody()
    return VisionScannersCreateBody
}

const visionScannersCreate = (): ToolBase<
    ReturnType<typeof VisionScannersCreateSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.ReplayScanner>>
> => ({
    name: 'vision-scanners-create',
    schema: VisionScannersCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.scanner_type !== undefined) {
            body['scanner_type'] = params.scanner_type
        }
        if (params.creation_method !== undefined) {
            body['creation_method'] = params.creation_method
        }
        if (params.scanner_config !== undefined) {
            body['scanner_config'] = params.scanner_config
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.sampling_rate !== undefined) {
            body['sampling_rate'] = params.sampling_rate
        }
        if (params.sampling_mode !== undefined) {
            body['sampling_mode'] = params.sampling_mode
        }
        if (params.credit_limit !== undefined) {
            body['credit_limit'] = params.credit_limit
        }
        if (params.provider !== undefined) {
            body['provider'] = params.provider
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.emits_signals !== undefined) {
            body['emits_signals'] = params.emits_signals
        }
        if (params.experiment_targeting !== undefined) {
            body['experiment_targeting'] = params.experiment_targeting
        }
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/`,
            body,
        })
        return withAgentNote(
            await withPostHogUrl(context, result, `/replay-vision/${result.id}`),
            'A new scanner runs the prompt as written, and the first sweep is where its weaknesses show. Tell the person that rating its results thumbs up or down turns into a config recommendation they can review, and that `_posthogUrl` opens the scanner where they do it. There is nothing to rate yet, so this is a closing sentence for them, not a step for you.\n'
        )
    },
})

const VisionScannersDeleteSchema = () => {
    const VisionScannersDestroyParams = orvalSchemas.VisionScannersDestroyParams()
    return VisionScannersDestroyParams.omit({ project_id: true })
}

const visionScannersDelete = (): ToolBase<ReturnType<typeof VisionScannersDeleteSchema>, unknown> => ({
    name: 'vision-scanners-delete',
    schema: VisionScannersDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersDraftSchema = () => {
    const VisionScannersDraftCreateBody = orvalSchemas.VisionScannersDraftCreateBody()
    return VisionScannersDraftCreateBody
}

const visionScannersDraft = (): ToolBase<
    ReturnType<typeof VisionScannersDraftSchema>,
    Schemas.DraftScannerResponse
> => ({
    name: 'vision-scanners-draft',
    schema: VisionScannersDraftSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersDraftSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.monthly_credit_budget !== undefined) {
            body['monthly_credit_budget'] = params.monthly_credit_budget
        }
        const result = await context.api.request<Schemas.DraftScannerResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/draft/`,
            body,
        })
        return result
    },
})

const VisionScannersDuplicateSchema = () => {
    const VisionScannersDuplicateCreateParams = orvalSchemas.VisionScannersDuplicateCreateParams()
    return VisionScannersDuplicateCreateParams.omit({ project_id: true })
}

const visionScannersDuplicate = (): ToolBase<
    ReturnType<typeof VisionScannersDuplicateSchema>,
    WithPostHogUrl<Schemas.ReplayScanner>
> => ({
    name: 'vision-scanners-duplicate',
    schema: VisionScannersDuplicateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersDuplicateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/duplicate/`,
        })
        return await withPostHogUrl(context, result, `/replay-vision/${result.id}`)
    },
})

const VisionScannersEstimateCreateSchema = () => {
    const VisionScannersEstimateCreateBody = orvalSchemas.VisionScannersEstimateCreateBody()
    return VisionScannersEstimateCreateBody
}

const visionScannersEstimateCreate = (): ToolBase<
    ReturnType<typeof VisionScannersEstimateCreateSchema>,
    Schemas.EstimateResponse
> => ({
    name: 'vision-scanners-estimate-create',
    schema: VisionScannersEstimateCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersEstimateCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.sampling_rate !== undefined) {
            body['sampling_rate'] = params.sampling_rate
        }
        if (params.sampling_mode !== undefined) {
            body['sampling_mode'] = params.sampling_mode
        }
        if (params.scanner_id !== undefined) {
            body['scanner_id'] = params.scanner_id
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.experiment_targeting !== undefined) {
            body['experiment_targeting'] = params.experiment_targeting
        }
        const result = await context.api.request<Schemas.EstimateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/estimate/`,
            body,
        })
        return result
    },
})

const VisionScannersGetSchema = () => {
    const VisionScannersRetrieveParams = orvalSchemas.VisionScannersRetrieveParams()
    return VisionScannersRetrieveParams.omit({ project_id: true })
}

const visionScannersGet = (): ToolBase<ReturnType<typeof VisionScannersGetSchema>, Schemas.ReplayScanner> => ({
    name: 'vision-scanners-get',
    schema: VisionScannersGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersImpactRetrieveSchema = () => {
    const VisionScannersImpactRetrieveParams = orvalSchemas.VisionScannersImpactRetrieveParams()
    const VisionScannersImpactRetrieveQueryParams = orvalSchemas.VisionScannersImpactRetrieveQueryParams()
    return VisionScannersImpactRetrieveParams.omit({ project_id: true }).extend(
        VisionScannersImpactRetrieveQueryParams.shape
    )
}

const visionScannersImpactRetrieve = (): ToolBase<
    ReturnType<typeof VisionScannersImpactRetrieveSchema>,
    Schemas.ScannerImpact
> => ({
    name: 'vision-scanners-impact-retrieve',
    schema: VisionScannersImpactRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersImpactRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScannerImpact>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/impact/`,
            query: {
                max_score: params.max_score,
                min_score: params.min_score,
                tag: params.tag,
                window_days: params.window_days,
            },
        })
        return result
    },
})

const VisionScannersInlineScanCreateSchema = () => {
    const VisionScannersInlineScanCreateBody = orvalSchemas.VisionScannersInlineScanCreateBody()
    return VisionScannersInlineScanCreateBody
}

const visionScannersInlineScanCreate = (): ToolBase<ReturnType<typeof VisionScannersInlineScanCreateSchema>, unknown> =>
    withUiApp('inline-scan', {
        name: 'vision-scanners-inline-scan-create',
        schema: VisionScannersInlineScanCreateSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersInlineScanCreateSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.session_ids !== undefined) {
                body['session_ids'] = params.session_ids
            }
            if (params.prompt !== undefined) {
                body['prompt'] = params.prompt
            }
            if (params.scanner_type !== undefined) {
                body['scanner_type'] = params.scanner_type
            }
            if (params.scanner_config !== undefined) {
                body['scanner_config'] = params.scanner_config
            }
            if (params.model !== undefined) {
                body['model'] = params.model
            }
            const result = await context.api.request<unknown>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/inline_scan/`,
                body,
            })
            return result
        },
    })

const VisionScannersListSchema = () => {
    const VisionScannersListQueryParams = orvalSchemas.VisionScannersListQueryParams()
    return VisionScannersListQueryParams.extend({
        enabled: z
            .preprocess(
                castBooleanToString,
                VisionScannersListQueryParams.shape['enabled'].describe(
                    'Filter by enabled state. Accepts `enabled`, `disabled`, a comma-separated list of both, or the boolean form `true` / `false`. Omit to list every scanner.'
                )
            )
            .optional(),
    })
}

const visionScannersList = (): ToolBase<
    ReturnType<typeof VisionScannersListSchema>,
    WithPostHogUrl<Schemas.PaginatedReplayScannerList>
> => ({
    name: 'vision-scanners-list',
    schema: VisionScannersListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReplayScannerList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/`,
            query: {
                created_by: params.created_by,
                emits_signals: params.emits_signals,
                enabled: params.enabled,
                experiment_id: params.experiment_id,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                scanner_type: params.scanner_type,
                search: params.search,
                tags: params.tags,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionScannersObservationsGetSchema = () => {
    const VisionScannersObservationsRetrieveParams = orvalSchemas.VisionScannersObservationsRetrieveParams()
    const VisionScannersObservationsRetrieveQueryParams = orvalSchemas.VisionScannersObservationsRetrieveQueryParams()
    return VisionScannersObservationsRetrieveParams.omit({ project_id: true }).extend(
        VisionScannersObservationsRetrieveQueryParams.shape
    )
}

const visionScannersObservationsGet = (): ToolBase<
    ReturnType<typeof VisionScannersObservationsGetSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.ReplayObservation>>
> => ({
    name: 'vision-scanners-observations-get',
    schema: VisionScannersObservationsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersObservationsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayObservation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/${encodeURIComponent(String(params.id))}/`,
            query: {
                backfill_id: params.backfill_id,
                date_from: params.date_from,
                date_to: params.date_to,
                labeled: params.labeled,
                max_score: params.max_score,
                min_score: params.min_score,
                order_by: params.order_by,
                recording_subject: params.recording_subject,
                session_id: params.session_id,
                status: params.status,
                tags: params.tags,
                triggered_by: params.triggered_by,
                verdict: params.verdict,
            },
        })
        return withAgentNote(
            await withPostHogUrl(context, result, `/replay/${result.session_id}`),
            "`_posthogUrl` opens the recording this observation analysed. `scanner_result.model_output.reasoning_segments` interleaves prose with `chip` segments, and a chip's `timestamp_ms` is the recording-relative offset of the moment being cited — append `?t=<seconds>` (`timestamp_ms` / 1000, rounded down) to that URL to seek straight to it. When you report a finding to someone, deep-link the one or two moments it turns on rather than only describing them.\n"
        )
    },
})

const VisionScannersObservationsListSchema = () => {
    const VisionScannersObservationsListParams = orvalSchemas.VisionScannersObservationsListParams()
    const VisionScannersObservationsListQueryParams = orvalSchemas.VisionScannersObservationsListQueryParams()
    return VisionScannersObservationsListParams.omit({ project_id: true }).extend(
        VisionScannersObservationsListQueryParams.shape
    )
}

const visionScannersObservationsList = (): ToolBase<
    ReturnType<typeof VisionScannersObservationsListSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.PaginatedReplayObservationList>>
> =>
    withUiApp('vision-observation-list', {
        name: 'vision-scanners-observations-list',
        schema: VisionScannersObservationsListSchema(),
        handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersObservationsListSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedReplayObservationList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/`,
                query: {
                    backfill_id: params.backfill_id,
                    date_from: params.date_from,
                    date_to: params.date_to,
                    labeled: params.labeled,
                    limit: params.limit,
                    max_score: params.max_score,
                    min_score: params.min_score,
                    offset: params.offset,
                    order_by: params.order_by,
                    recording_subject: params.recording_subject,
                    session_id: params.session_id,
                    status: params.status,
                    tags: params.tags,
                    triggered_by: params.triggered_by,
                    verdict: params.verdict,
                },
            })
            return withAgentNote(
                await withPostHogUrl(
                    context,
                    {
                        ...result,
                        results: await Promise.all(
                            (result.results ?? []).map((item) =>
                                withPostHogUrl(context, item, `/replay/${item.session_id}`)
                            )
                        ),
                    },
                    '/replay'
                ),
                "Each observation's `_posthogUrl` opens the recording it analysed. `scanner_result.model_output.reasoning_segments` interleaves prose with `chip` segments, and a chip's `timestamp_ms` is the recording-relative offset of the moment being cited — append `?t=<seconds>` (`timestamp_ms` / 1000, rounded down) to that URL to seek straight to it. When you report a finding to someone, deep-link the one or two moments it turns on rather than only describing them. A rating is the person's verdict on whether the scanner was right, and it is what `vision-scanners-prompt-suggestions-generate` learns the config from, so ask them for it and record what they say with `vision-observations-label-create`. Never rate from your own reading of the result: the rating is team-wide, and a scanner's output can repeat text from the recording it analysed.\n"
            )
        },
    })

const VisionScannersObservationsStatsSchema = () => {
    const VisionScannersObservationsStatsRetrieveParams = orvalSchemas.VisionScannersObservationsStatsRetrieveParams()
    const VisionScannersObservationsStatsRetrieveQueryParams =
        orvalSchemas.VisionScannersObservationsStatsRetrieveQueryParams()
    return VisionScannersObservationsStatsRetrieveParams.omit({ project_id: true }).extend(
        VisionScannersObservationsStatsRetrieveQueryParams.shape
    )
}

const visionScannersObservationsStats = (): ToolBase<
    ReturnType<typeof VisionScannersObservationsStatsSchema>,
    WithAgentNote<Schemas.ObservationStats>
> => ({
    name: 'vision-scanners-observations-stats',
    schema: VisionScannersObservationsStatsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersObservationsStatsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ObservationStats>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/stats/`,
            query: {
                backfill_id: params.backfill_id,
                date_from: params.date_from,
                date_to: params.date_to,
                labeled: params.labeled,
                max_score: params.max_score,
                min_score: params.min_score,
                recent_days: params.recent_days,
                recording_subject: params.recording_subject,
                session_id: params.session_id,
                status: params.status,
                tags: params.tags,
                triggered_by: params.triggered_by,
                verdict: params.verdict,
            },
        })
        return withAgentNote(
            result,
            "When `status_counts.succeeded` is above 10 and `labels.up_total` + `labels.down_total` is under 5, this scanner has results almost nobody has rated, so a prompt suggestion has little to learn from. Say so, and ask the person to rate a few results before you call `vision-scanners-prompt-suggestions-generate`. Record their verdicts with `vision-observations-label-create` rather than supplying your own. Testing a suggestion is not available over MCP, so tell them to test it on the scanner's Calibration tab before they apply it.\n"
        )
    },
})

const VisionScannersPromptSuggestionsApplySchema = () => {
    const VisionScannersPromptSuggestionsApplyCreateBody = orvalSchemas.VisionScannersPromptSuggestionsApplyCreateBody()
    const VisionScannersPromptSuggestionsApplyCreateParams =
        orvalSchemas.VisionScannersPromptSuggestionsApplyCreateParams()
    return VisionScannersPromptSuggestionsApplyCreateParams.omit({ project_id: true }).extend(
        VisionScannersPromptSuggestionsApplyCreateBody.shape
    )
}

const visionScannersPromptSuggestionsApply = (): ToolBase<
    ReturnType<typeof VisionScannersPromptSuggestionsApplySchema>,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-apply',
    schema: VisionScannersPromptSuggestionsApplySchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof VisionScannersPromptSuggestionsApplySchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.ReplayScannerPromptSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/${encodeURIComponent(String(params.id))}/apply/`,
            body,
        })
        return result
    },
})

const VisionScannersPromptSuggestionsCurrentSchema = () => {
    const VisionScannersPromptSuggestionsCurrentRetrieveParams =
        orvalSchemas.VisionScannersPromptSuggestionsCurrentRetrieveParams()
    return VisionScannersPromptSuggestionsCurrentRetrieveParams.omit({ project_id: true })
}

const visionScannersPromptSuggestionsCurrent = (): ToolBase<
    ReturnType<typeof VisionScannersPromptSuggestionsCurrentSchema>,
    Schemas.CurrentPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-current',
    schema: VisionScannersPromptSuggestionsCurrentSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof VisionScannersPromptSuggestionsCurrentSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CurrentPromptSuggestion>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/current/`,
        })
        return result
    },
})

const VisionScannersPromptSuggestionsDismissSchema = () => {
    const VisionScannersPromptSuggestionsDismissCreateParams =
        orvalSchemas.VisionScannersPromptSuggestionsDismissCreateParams()
    return VisionScannersPromptSuggestionsDismissCreateParams.omit({ project_id: true })
}

const visionScannersPromptSuggestionsDismiss = (): ToolBase<
    ReturnType<typeof VisionScannersPromptSuggestionsDismissSchema>,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-dismiss',
    schema: VisionScannersPromptSuggestionsDismissSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof VisionScannersPromptSuggestionsDismissSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerPromptSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/${encodeURIComponent(String(params.id))}/dismiss/`,
        })
        return result
    },
})

const VisionScannersPromptSuggestionsGenerateSchema = () => {
    const VisionScannersPromptSuggestionsGenerateCreateParams =
        orvalSchemas.VisionScannersPromptSuggestionsGenerateCreateParams()
    return VisionScannersPromptSuggestionsGenerateCreateParams.omit({ project_id: true })
}

const visionScannersPromptSuggestionsGenerate = (): ToolBase<
    ReturnType<typeof VisionScannersPromptSuggestionsGenerateSchema>,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-generate',
    schema: VisionScannersPromptSuggestionsGenerateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof VisionScannersPromptSuggestionsGenerateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerPromptSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/generate/`,
        })
        return result
    },
})

const VisionScannersScanSessionSchema = () => {
    const VisionScannersObserveCreateBody = orvalSchemas.VisionScannersObserveCreateBody()
    const VisionScannersObserveCreateParams = orvalSchemas.VisionScannersObserveCreateParams()
    return VisionScannersObserveCreateParams.omit({ project_id: true }).extend(VisionScannersObserveCreateBody.shape)
}

const visionScannersScanSession = (): ToolBase<
    ReturnType<typeof VisionScannersScanSessionSchema>,
    Schemas.ObserveAlreadyScanned
> => ({
    name: 'vision-scanners-scan-session',
    schema: VisionScannersScanSessionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersScanSessionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.session_id !== undefined) {
            body['session_id'] = params.session_id
        }
        const result = await context.api.request<Schemas.ObserveAlreadyScanned>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/observe/`,
            body,
        })
        return result
    },
})

const VisionScannersScoutReportsListSchema = () => {
    const VisionScannersScoutReportsListParams = orvalSchemas.VisionScannersScoutReportsListParams()
    return VisionScannersScoutReportsListParams.omit({ project_id: true })
}

const visionScannersScoutReportsList = (): ToolBase<
    ReturnType<typeof VisionScannersScoutReportsListSchema>,
    WithPostHogUrl<Schemas.ScoutReport[]>
> => ({
    name: 'vision-scanners-scout-reports-list',
    schema: VisionScannersScoutReportsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersScoutReportsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScoutReport[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/scout_reports/`,
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionScannersScoutReportsGetSchema = () => {
    const VisionScannersScoutReportsRetrieveParams = orvalSchemas.VisionScannersScoutReportsRetrieveParams()
    return VisionScannersScoutReportsRetrieveParams.omit({ project_id: true })
}

const visionScannersScoutReportsGet = (): ToolBase<
    ReturnType<typeof VisionScannersScoutReportsGetSchema>,
    Schemas.ScoutReport
> => ({
    name: 'vision-scanners-scout-reports-get',
    schema: VisionScannersScoutReportsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersScoutReportsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScoutReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/scout_reports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersScoutsCreateSchema = () => {
    const VisionScannersScoutsCreateBody = orvalSchemas.VisionScannersScoutsCreateBody()
    const VisionScannersScoutsCreateParams = orvalSchemas.VisionScannersScoutsCreateParams()
    return VisionScannersScoutsCreateParams.omit({ project_id: true }).extend(VisionScannersScoutsCreateBody.shape)
}

const visionScannersScoutsCreate = (): ToolBase<
    ReturnType<typeof VisionScannersScoutsCreateSchema>,
    Schemas.ScannerScoutCreateResponse
> => ({
    name: 'vision-scanners-scouts-create',
    schema: VisionScannersScoutsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersScoutsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.display_name !== undefined) {
            body['display_name'] = params.display_name
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.ScannerScoutCreateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/scouts/`,
            body,
        })
        return result
    },
})

const VisionScannersSelfDrivingStatsSchema = () => {
    const VisionScannersSelfDrivingStatsRetrieveParams = orvalSchemas.VisionScannersSelfDrivingStatsRetrieveParams()
    return VisionScannersSelfDrivingStatsRetrieveParams.omit({ project_id: true })
}

const visionScannersSelfDrivingStats = (): ToolBase<
    ReturnType<typeof VisionScannersSelfDrivingStatsSchema>,
    Schemas.ScannerSelfDrivingStats
> => ({
    name: 'vision-scanners-self-driving-stats',
    schema: VisionScannersSelfDrivingStatsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersSelfDrivingStatsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScannerSelfDrivingStats>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/self_driving_stats/`,
        })
        return result
    },
})

const VisionScannersCountsSchema = () => z.object({})

const visionScannersCounts = (): ToolBase<
    ReturnType<typeof VisionScannersCountsSchema>,
    Schemas.ScannerStatsResponse
> => ({
    name: 'vision-scanners-counts',
    schema: VisionScannersCountsSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof VisionScannersCountsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScannerStatsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/stats/`,
        })
        return result
    },
})

const VisionScannersSuggestTagsSchema = () => {
    const VisionScannersSuggestTagsCreateBody = orvalSchemas.VisionScannersSuggestTagsCreateBody()
    return VisionScannersSuggestTagsCreateBody
}

const visionScannersSuggestTags = (): ToolBase<
    ReturnType<typeof VisionScannersSuggestTagsSchema>,
    Schemas.SuggestTagsResponse
> => ({
    name: 'vision-scanners-suggest-tags',
    schema: VisionScannersSuggestTagsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersSuggestTagsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.multi_label !== undefined) {
            body['multi_label'] = params.multi_label
        }
        if (params.allow_freeform_tags !== undefined) {
            body['allow_freeform_tags'] = params.allow_freeform_tags
        }
        if (params.scanner_id !== undefined) {
            body['scanner_id'] = params.scanner_id
        }
        const result = await context.api.request<Schemas.SuggestTagsResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/suggest_tags/`,
            body,
        })
        return result
    },
})

const VisionScannersUpdateSchema = () => {
    const VisionScannersPartialUpdateBody = orvalSchemas.VisionScannersPartialUpdateBody()
    const VisionScannersPartialUpdateParams = orvalSchemas.VisionScannersPartialUpdateParams()
    return VisionScannersPartialUpdateParams.omit({ project_id: true }).extend(VisionScannersPartialUpdateBody.shape)
}

const visionScannersUpdate = (): ToolBase<ReturnType<typeof VisionScannersUpdateSchema>, Schemas.ReplayScanner> => ({
    name: 'vision-scanners-update',
    schema: VisionScannersUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.scanner_type !== undefined) {
            body['scanner_type'] = params.scanner_type
        }
        if (params.creation_method !== undefined) {
            body['creation_method'] = params.creation_method
        }
        if (params.scanner_config !== undefined) {
            body['scanner_config'] = params.scanner_config
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.sampling_rate !== undefined) {
            body['sampling_rate'] = params.sampling_rate
        }
        if (params.sampling_mode !== undefined) {
            body['sampling_mode'] = params.sampling_mode
        }
        if (params.credit_limit !== undefined) {
            body['credit_limit'] = params.credit_limit
        }
        if (params.provider !== undefined) {
            body['provider'] = params.provider
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.emits_signals !== undefined) {
            body['emits_signals'] = params.emits_signals
        }
        if (params.experiment_targeting !== undefined) {
            body['experiment_targeting'] = params.experiment_targeting
        }
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const VisionScannersWatchFeedSchema = () => {
    const VisionScannersWatchFeedRetrieveQueryParams = orvalSchemas.VisionScannersWatchFeedRetrieveQueryParams()
    return VisionScannersWatchFeedRetrieveQueryParams
}

const visionScannersWatchFeed = (): ToolBase<
    ReturnType<typeof VisionScannersWatchFeedSchema>,
    WithAgentNote<Schemas.WatchFeedResponse>
> => ({
    name: 'vision-scanners-watch-feed',
    schema: VisionScannersWatchFeedSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionScannersWatchFeedSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WatchFeedResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/watch_feed/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                scanner_ids: params.scanner_ids,
                scanner_type: params.scanner_type,
                search: params.search,
                tags: params.tags,
            },
        })
        return withAgentNote(
            result,
            'Point the person at one or two recordings with a one-line reason each, rather than listing the whole feed.\n'
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'vision-quota-spend-series-get': visionQuotaSpendSeriesGet,
    'vision-alerts-create': visionAlertsCreate,
    'vision-alerts-destinations-create': visionAlertsDestinationsCreate,
    'vision-alerts-destinations-delete': visionAlertsDestinationsDelete,
    'vision-alerts-delete': visionAlertsDelete,
    'vision-alerts-events-list': visionAlertsEventsList,
    'vision-alerts-list': visionAlertsList,
    'vision-alerts-partial-update': visionAlertsPartialUpdate,
    'vision-alerts-reset': visionAlertsReset,
    'vision-alerts-get': visionAlertsGet,
    'vision-observations-create-task': visionObservationsCreateTask,
    'vision-observations-label-create': visionObservationsLabelCreate,
    'vision-observations-label-destroy': visionObservationsLabelDestroy,
    'vision-observations-list': visionObservationsList,
    'vision-observations-retrieve': visionObservationsRetrieve,
    'vision-observations-retry': visionObservationsRetry,
    'vision-observations-search': visionObservationsSearch,
    'vision-observations-signal-reports-list': visionObservationsSignalReportsList,
    'vision-quota-retrieve': visionQuotaRetrieve,
    'vision-scanners-affected-cohort-create': visionScannersAffectedCohortCreate,
    'vision-scanners-backfills-cancel': visionScannersBackfillsCancel,
    'vision-scanners-backfills-create': visionScannersBackfillsCreate,
    'vision-scanners-backfills-estimate': visionScannersBackfillsEstimate,
    'vision-scanners-backfills-list': visionScannersBackfillsList,
    'vision-scanners-backfills-resume': visionScannersBackfillsResume,
    'vision-scanners-backfills-get': visionScannersBackfillsGet,
    'vision-scanners-scan-sessions': visionScannersScanSessions,
    'vision-scanners-create': visionScannersCreate,
    'vision-scanners-delete': visionScannersDelete,
    'vision-scanners-draft': visionScannersDraft,
    'vision-scanners-duplicate': visionScannersDuplicate,
    'vision-scanners-estimate-create': visionScannersEstimateCreate,
    'vision-scanners-get': visionScannersGet,
    'vision-scanners-impact-retrieve': visionScannersImpactRetrieve,
    'vision-scanners-inline-scan-create': visionScannersInlineScanCreate,
    'vision-scanners-list': visionScannersList,
    'vision-scanners-observations-get': visionScannersObservationsGet,
    'vision-scanners-observations-list': visionScannersObservationsList,
    'vision-scanners-observations-stats': visionScannersObservationsStats,
    'vision-scanners-prompt-suggestions-apply': visionScannersPromptSuggestionsApply,
    'vision-scanners-prompt-suggestions-current': visionScannersPromptSuggestionsCurrent,
    'vision-scanners-prompt-suggestions-dismiss': visionScannersPromptSuggestionsDismiss,
    'vision-scanners-prompt-suggestions-generate': visionScannersPromptSuggestionsGenerate,
    'vision-scanners-scan-session': visionScannersScanSession,
    'vision-scanners-scout-reports-list': visionScannersScoutReportsList,
    'vision-scanners-scout-reports-get': visionScannersScoutReportsGet,
    'vision-scanners-scouts-create': visionScannersScoutsCreate,
    'vision-scanners-self-driving-stats': visionScannersSelfDrivingStats,
    'vision-scanners-counts': visionScannersCounts,
    'vision-scanners-suggest-tags': visionScannersSuggestTags,
    'vision-scanners-update': visionScannersUpdate,
    'vision-scanners-watch-feed': visionScannersWatchFeed,
}
