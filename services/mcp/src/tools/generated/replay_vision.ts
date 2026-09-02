// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/replay_vision/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, withAgentNote, type WithPostHogUrl, type WithAgentNote } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisionActionsCreateSchema = () => {
    const VisionActionsCreateBody = orvalSchemas.VisionActionsCreateBody()
    return VisionActionsCreateBody
}

const visionActionsCreate = (): ToolBase<ReturnType<typeof VisionActionsCreateSchema>, Schemas.VisionAction> => ({
    name: 'vision-actions-create',
    schema: VisionActionsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.scanner !== undefined) {
            body['scanner'] = params.scanner
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.is_scanner_digest !== undefined) {
            body['is_scanner_digest'] = params.is_scanner_digest
        }
        if (params.trigger_type !== undefined) {
            body['trigger_type'] = params.trigger_type
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        if (params.trigger_config !== undefined) {
            body['trigger_config'] = params.trigger_config
        }
        if (params.selection !== undefined) {
            body['selection'] = params.selection
        }
        if (params.synthesis_config !== undefined) {
            body['synthesis_config'] = params.synthesis_config
        }
        if (params.alert_config !== undefined) {
            body['alert_config'] = params.alert_config
        }
        if (params.delivery_config !== undefined) {
            body['delivery_config'] = params.delivery_config
        }
        const result = await context.api.request<Schemas.VisionAction>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/`,
            body,
        })
        return result
    },
})

const VisionActionsDeleteSchema = () => {
    const VisionActionsDestroyParams = orvalSchemas.VisionActionsDestroyParams()
    return VisionActionsDestroyParams.omit({ project_id: true })
}

const visionActionsDelete = (): ToolBase<ReturnType<typeof VisionActionsDeleteSchema>, unknown> => ({
    name: 'vision-actions-delete',
    schema: VisionActionsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsListSchema = () => {
    const VisionActionsListQueryParams = orvalSchemas.VisionActionsListQueryParams()
    return VisionActionsListQueryParams
}

const visionActionsList = (): ToolBase<
    ReturnType<typeof VisionActionsListSchema>,
    WithPostHogUrl<Schemas.PaginatedVisionActionList>
> => ({
    name: 'vision-actions-list',
    schema: VisionActionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedVisionActionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                scanner: params.scanner,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionActionsRetrieveSchema = () => {
    const VisionActionsRetrieveParams = orvalSchemas.VisionActionsRetrieveParams()
    return VisionActionsRetrieveParams.omit({ project_id: true })
}

const visionActionsRetrieve = (): ToolBase<ReturnType<typeof VisionActionsRetrieveSchema>, Schemas.VisionAction> => ({
    name: 'vision-actions-retrieve',
    schema: VisionActionsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionAction>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsRunsListSchema = () => {
    const VisionActionsRunsListParams = orvalSchemas.VisionActionsRunsListParams()
    const VisionActionsRunsListQueryParams = orvalSchemas.VisionActionsRunsListQueryParams()
    return VisionActionsRunsListParams.omit({ project_id: true }).extend(VisionActionsRunsListQueryParams.shape)
}

const visionActionsRunsList = (): ToolBase<
    ReturnType<typeof VisionActionsRunsListSchema>,
    WithPostHogUrl<Schemas.PaginatedVisionActionRunListList>
> => ({
    name: 'vision-actions-runs-list',
    schema: VisionActionsRunsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsRunsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedVisionActionRunListList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.vision_action_id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionActionsRunsRetrieveSchema = () => {
    const VisionActionsRunsRetrieveParams = orvalSchemas.VisionActionsRunsRetrieveParams()
    return VisionActionsRunsRetrieveParams.omit({ project_id: true })
}

const visionActionsRunsRetrieve = (): ToolBase<
    ReturnType<typeof VisionActionsRunsRetrieveSchema>,
    Schemas.VisionActionRun
> => ({
    name: 'vision-actions-runs-retrieve',
    schema: VisionActionsRunsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsRunsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionActionRun>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.vision_action_id))}/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsUpdateSchema = () => {
    const VisionActionsPartialUpdateBody = orvalSchemas.VisionActionsPartialUpdateBody()
    const VisionActionsPartialUpdateParams = orvalSchemas.VisionActionsPartialUpdateParams()
    return VisionActionsPartialUpdateParams.omit({ project_id: true }).extend(VisionActionsPartialUpdateBody.shape)
}

const visionActionsUpdate = (): ToolBase<ReturnType<typeof VisionActionsUpdateSchema>, Schemas.VisionAction> => ({
    name: 'vision-actions-update',
    schema: VisionActionsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof VisionActionsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.scanner !== undefined) {
            body['scanner'] = params.scanner
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.is_scanner_digest !== undefined) {
            body['is_scanner_digest'] = params.is_scanner_digest
        }
        if (params.trigger_type !== undefined) {
            body['trigger_type'] = params.trigger_type
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        if (params.trigger_config !== undefined) {
            body['trigger_config'] = params.trigger_config
        }
        if (params.selection !== undefined) {
            body['selection'] = params.selection
        }
        if (params.synthesis_config !== undefined) {
            body['synthesis_config'] = params.synthesis_config
        }
        if (params.alert_config !== undefined) {
            body['alert_config'] = params.alert_config
        }
        if (params.delivery_config !== undefined) {
            body['delivery_config'] = params.delivery_config
        }
        const result = await context.api.request<Schemas.VisionAction>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.id))}/`,
            body,
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

const VisionScannersCreateSchema = () => {
    const VisionScannersCreateBody = orvalSchemas.VisionScannersCreateBody()
    return VisionScannersCreateBody
}

const visionScannersCreate = (): ToolBase<ReturnType<typeof VisionScannersCreateSchema>, Schemas.ReplayScanner> => ({
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
        return result
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
    return VisionScannersListQueryParams
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
                "Each observation's `_posthogUrl` opens the recording it analysed. `scanner_result.model_output.reasoning_segments` interleaves prose with `chip` segments, and a chip's `timestamp_ms` is the recording-relative offset of the moment being cited — append `?t=<seconds>` (`timestamp_ms` / 1000, rounded down) to that URL to seek straight to it. When you report a finding to someone, deep-link the one or two moments it turns on rather than only describing them.\n"
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
    Schemas.ObservationStats
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
        return result
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'vision-actions-create': visionActionsCreate,
    'vision-actions-delete': visionActionsDelete,
    'vision-actions-list': visionActionsList,
    'vision-actions-retrieve': visionActionsRetrieve,
    'vision-actions-runs-list': visionActionsRunsList,
    'vision-actions-runs-retrieve': visionActionsRunsRetrieve,
    'vision-actions-update': visionActionsUpdate,
    'vision-observations-label-create': visionObservationsLabelCreate,
    'vision-observations-label-destroy': visionObservationsLabelDestroy,
    'vision-observations-list': visionObservationsList,
    'vision-observations-retrieve': visionObservationsRetrieve,
    'vision-observations-search': visionObservationsSearch,
    'vision-quota-retrieve': visionQuotaRetrieve,
    'vision-scanners-affected-cohort-create': visionScannersAffectedCohortCreate,
    'vision-scanners-create': visionScannersCreate,
    'vision-scanners-delete': visionScannersDelete,
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
    'vision-scanners-update': visionScannersUpdate,
}
