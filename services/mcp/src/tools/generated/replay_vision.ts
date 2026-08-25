// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisionActionsCreateBody,
    VisionActionsDestroyParams,
    VisionActionsListQueryParams,
    VisionActionsPartialUpdateBody,
    VisionActionsPartialUpdateParams,
    VisionActionsRetrieveParams,
    VisionActionsRunsListParams,
    VisionActionsRunsListQueryParams,
    VisionActionsRunsRetrieveParams,
    VisionObservationsLabelCreateBody,
    VisionObservationsLabelCreateParams,
    VisionObservationsLabelDestroyParams,
    VisionObservationsListQueryParams,
    VisionObservationsRetrieveParams,
    VisionObservationsRetrieveQueryParams,
    VisionScannersAffectedCohortCreateBody,
    VisionScannersAffectedCohortCreateParams,
    VisionScannersCreateBody,
    VisionScannersDestroyParams,
    VisionScannersEstimateCreateBody,
    VisionScannersImpactRetrieveParams,
    VisionScannersImpactRetrieveQueryParams,
    VisionScannersInlineScanCreateBody,
    VisionScannersListQueryParams,
    VisionScannersObservationsListParams,
    VisionScannersObservationsListQueryParams,
    VisionScannersObservationsRetrieveParams,
    VisionScannersObservationsRetrieveQueryParams,
    VisionScannersObservationsStatsRetrieveParams,
    VisionScannersObservationsStatsRetrieveQueryParams,
    VisionScannersObserveCreateBody,
    VisionScannersObserveCreateParams,
    VisionScannersPartialUpdateBody,
    VisionScannersPartialUpdateParams,
    VisionScannersPromptSuggestionsApplyCreateBody,
    VisionScannersPromptSuggestionsApplyCreateParams,
    VisionScannersPromptSuggestionsCurrentRetrieveParams,
    VisionScannersPromptSuggestionsDismissCreateParams,
    VisionScannersPromptSuggestionsGenerateCreateParams,
    VisionScannersRetrieveParams,
} from '@/generated/replay_vision/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, withAgentNote, type WithPostHogUrl, type WithAgentNote } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisionActionsCreateSchema = VisionActionsCreateBody

const visionActionsCreate = (): ToolBase<typeof VisionActionsCreateSchema, Schemas.VisionAction> => ({
    name: 'vision-actions-create',
    schema: VisionActionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsCreateSchema>) => {
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

const VisionActionsDeleteSchema = VisionActionsDestroyParams.omit({ project_id: true })

const visionActionsDelete = (): ToolBase<typeof VisionActionsDeleteSchema, unknown> => ({
    name: 'vision-actions-delete',
    schema: VisionActionsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsListSchema = VisionActionsListQueryParams

const visionActionsList = (): ToolBase<
    typeof VisionActionsListSchema,
    WithPostHogUrl<Schemas.PaginatedVisionActionList>
> => ({
    name: 'vision-actions-list',
    schema: VisionActionsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsListSchema>) => {
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

const VisionActionsRetrieveSchema = VisionActionsRetrieveParams.omit({ project_id: true })

const visionActionsRetrieve = (): ToolBase<typeof VisionActionsRetrieveSchema, Schemas.VisionAction> => ({
    name: 'vision-actions-retrieve',
    schema: VisionActionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionAction>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsRunsListSchema = VisionActionsRunsListParams.omit({ project_id: true }).extend(
    VisionActionsRunsListQueryParams.shape
)

const visionActionsRunsList = (): ToolBase<
    typeof VisionActionsRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedVisionActionRunListList>
> => ({
    name: 'vision-actions-runs-list',
    schema: VisionActionsRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsRunsListSchema>) => {
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

const VisionActionsRunsRetrieveSchema = VisionActionsRunsRetrieveParams.omit({ project_id: true })

const visionActionsRunsRetrieve = (): ToolBase<typeof VisionActionsRunsRetrieveSchema, Schemas.VisionActionRun> => ({
    name: 'vision-actions-runs-retrieve',
    schema: VisionActionsRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionActionRun>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/actions/${encodeURIComponent(String(params.vision_action_id))}/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionActionsUpdateSchema = VisionActionsPartialUpdateParams.omit({ project_id: true }).extend(
    VisionActionsPartialUpdateBody.shape
)

const visionActionsUpdate = (): ToolBase<typeof VisionActionsUpdateSchema, Schemas.VisionAction> => ({
    name: 'vision-actions-update',
    schema: VisionActionsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionActionsUpdateSchema>) => {
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

const VisionObservationsLabelCreateSchema = VisionObservationsLabelCreateParams.omit({ project_id: true }).extend(
    VisionObservationsLabelCreateBody.shape
)

const visionObservationsLabelCreate = (): ToolBase<
    typeof VisionObservationsLabelCreateSchema,
    Schemas.ReplayObservationLabel
> => ({
    name: 'vision-observations-label-create',
    schema: VisionObservationsLabelCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionObservationsLabelCreateSchema>) => {
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

const VisionObservationsLabelDestroySchema = VisionObservationsLabelDestroyParams.omit({ project_id: true })

const visionObservationsLabelDestroy = (): ToolBase<typeof VisionObservationsLabelDestroySchema, unknown> => ({
    name: 'vision-observations-label-destroy',
    schema: VisionObservationsLabelDestroySchema,
    handler: async (context: Context, params: z.infer<typeof VisionObservationsLabelDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/label/`,
        })
        return result
    },
})

const VisionObservationsListSchema = VisionObservationsListQueryParams

const visionObservationsList = (): ToolBase<
    typeof VisionObservationsListSchema,
    WithAgentNote<WithPostHogUrl<Schemas.PaginatedReplayObservationList>>
> =>
    withUiApp('vision-observation-list', {
        name: 'vision-observations-list',
        schema: VisionObservationsListSchema,
        handler: async (context: Context, params: z.infer<typeof VisionObservationsListSchema>) => {
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

const VisionObservationsRetrieveSchema = VisionObservationsRetrieveParams.omit({ project_id: true }).extend(
    VisionObservationsRetrieveQueryParams.shape
)

const visionObservationsRetrieve = (): ToolBase<
    typeof VisionObservationsRetrieveSchema,
    WithAgentNote<WithPostHogUrl<Schemas.ReplayObservation>>
> => ({
    name: 'vision-observations-retrieve',
    schema: VisionObservationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisionObservationsRetrieveSchema>) => {
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

const VisionQuotaRetrieveSchema = z.object({})

const visionQuotaRetrieve = (): ToolBase<typeof VisionQuotaRetrieveSchema, Schemas.VisionQuota> => ({
    name: 'vision-quota-retrieve',
    schema: VisionQuotaRetrieveSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof VisionQuotaRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.VisionQuota>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/quota/`,
        })
        return result
    },
})

const VisionScannersAffectedCohortCreateSchema = VisionScannersAffectedCohortCreateParams.omit({
    project_id: true,
}).extend(VisionScannersAffectedCohortCreateBody.shape)

const visionScannersAffectedCohortCreate = (): ToolBase<
    typeof VisionScannersAffectedCohortCreateSchema,
    Schemas.AffectedCohortResponse
> => ({
    name: 'vision-scanners-affected-cohort-create',
    schema: VisionScannersAffectedCohortCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersAffectedCohortCreateSchema>) => {
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

const VisionScannersCreateSchema = VisionScannersCreateBody

const visionScannersCreate = (): ToolBase<typeof VisionScannersCreateSchema, Schemas.ReplayScanner> => ({
    name: 'vision-scanners-create',
    schema: VisionScannersCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersCreateSchema>) => {
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

const VisionScannersDeleteSchema = VisionScannersDestroyParams.omit({ project_id: true })

const visionScannersDelete = (): ToolBase<typeof VisionScannersDeleteSchema, unknown> => ({
    name: 'vision-scanners-delete',
    schema: VisionScannersDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersEstimateCreateSchema = VisionScannersEstimateCreateBody

const visionScannersEstimateCreate = (): ToolBase<
    typeof VisionScannersEstimateCreateSchema,
    Schemas.EstimateResponse
> => ({
    name: 'vision-scanners-estimate-create',
    schema: VisionScannersEstimateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersEstimateCreateSchema>) => {
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

const VisionScannersGetSchema = VisionScannersRetrieveParams.omit({ project_id: true })

const visionScannersGet = (): ToolBase<typeof VisionScannersGetSchema, Schemas.ReplayScanner> => ({
    name: 'vision-scanners-get',
    schema: VisionScannersGetSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersImpactRetrieveSchema = VisionScannersImpactRetrieveParams.omit({ project_id: true }).extend(
    VisionScannersImpactRetrieveQueryParams.shape
)

const visionScannersImpactRetrieve = (): ToolBase<
    typeof VisionScannersImpactRetrieveSchema,
    Schemas.ScannerImpact
> => ({
    name: 'vision-scanners-impact-retrieve',
    schema: VisionScannersImpactRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersImpactRetrieveSchema>) => {
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

const VisionScannersInlineScanCreateSchema = VisionScannersInlineScanCreateBody

const visionScannersInlineScanCreate = (): ToolBase<typeof VisionScannersInlineScanCreateSchema, unknown> =>
    withUiApp('inline-scan', {
        name: 'vision-scanners-inline-scan-create',
        schema: VisionScannersInlineScanCreateSchema,
        handler: async (context: Context, params: z.infer<typeof VisionScannersInlineScanCreateSchema>) => {
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

const VisionScannersListSchema = VisionScannersListQueryParams

const visionScannersList = (): ToolBase<
    typeof VisionScannersListSchema,
    WithPostHogUrl<Schemas.PaginatedReplayScannerList>
> => ({
    name: 'vision-scanners-list',
    schema: VisionScannersListSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersListSchema>) => {
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

const VisionScannersObservationsGetSchema = VisionScannersObservationsRetrieveParams.omit({ project_id: true }).extend(
    VisionScannersObservationsRetrieveQueryParams.shape
)

const visionScannersObservationsGet = (): ToolBase<
    typeof VisionScannersObservationsGetSchema,
    WithAgentNote<WithPostHogUrl<Schemas.ReplayObservation>>
> => ({
    name: 'vision-scanners-observations-get',
    schema: VisionScannersObservationsGetSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersObservationsGetSchema>) => {
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

const VisionScannersObservationsListSchema = VisionScannersObservationsListParams.omit({ project_id: true }).extend(
    VisionScannersObservationsListQueryParams.shape
)

const visionScannersObservationsList = (): ToolBase<
    typeof VisionScannersObservationsListSchema,
    WithAgentNote<WithPostHogUrl<Schemas.PaginatedReplayObservationList>>
> =>
    withUiApp('vision-observation-list', {
        name: 'vision-scanners-observations-list',
        schema: VisionScannersObservationsListSchema,
        handler: async (context: Context, params: z.infer<typeof VisionScannersObservationsListSchema>) => {
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

const VisionScannersObservationsStatsSchema = VisionScannersObservationsStatsRetrieveParams.omit({
    project_id: true,
}).extend(VisionScannersObservationsStatsRetrieveQueryParams.shape)

const visionScannersObservationsStats = (): ToolBase<
    typeof VisionScannersObservationsStatsSchema,
    Schemas.ObservationStats
> => ({
    name: 'vision-scanners-observations-stats',
    schema: VisionScannersObservationsStatsSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersObservationsStatsSchema>) => {
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

const VisionScannersPromptSuggestionsApplySchema = VisionScannersPromptSuggestionsApplyCreateParams.omit({
    project_id: true,
}).extend(VisionScannersPromptSuggestionsApplyCreateBody.shape)

const visionScannersPromptSuggestionsApply = (): ToolBase<
    typeof VisionScannersPromptSuggestionsApplySchema,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-apply',
    schema: VisionScannersPromptSuggestionsApplySchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersPromptSuggestionsApplySchema>) => {
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

const VisionScannersPromptSuggestionsCurrentSchema = VisionScannersPromptSuggestionsCurrentRetrieveParams.omit({
    project_id: true,
})

const visionScannersPromptSuggestionsCurrent = (): ToolBase<
    typeof VisionScannersPromptSuggestionsCurrentSchema,
    Schemas.CurrentPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-current',
    schema: VisionScannersPromptSuggestionsCurrentSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersPromptSuggestionsCurrentSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CurrentPromptSuggestion>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/current/`,
        })
        return result
    },
})

const VisionScannersPromptSuggestionsDismissSchema = VisionScannersPromptSuggestionsDismissCreateParams.omit({
    project_id: true,
})

const visionScannersPromptSuggestionsDismiss = (): ToolBase<
    typeof VisionScannersPromptSuggestionsDismissSchema,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-dismiss',
    schema: VisionScannersPromptSuggestionsDismissSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersPromptSuggestionsDismissSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerPromptSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/${encodeURIComponent(String(params.id))}/dismiss/`,
        })
        return result
    },
})

const VisionScannersPromptSuggestionsGenerateSchema = VisionScannersPromptSuggestionsGenerateCreateParams.omit({
    project_id: true,
})

const visionScannersPromptSuggestionsGenerate = (): ToolBase<
    typeof VisionScannersPromptSuggestionsGenerateSchema,
    Schemas.ReplayScannerPromptSuggestion
> => ({
    name: 'vision-scanners-prompt-suggestions-generate',
    schema: VisionScannersPromptSuggestionsGenerateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersPromptSuggestionsGenerateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayScannerPromptSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/prompt_suggestions/generate/`,
        })
        return result
    },
})

const VisionScannersScanSessionSchema = VisionScannersObserveCreateParams.omit({ project_id: true }).extend(
    VisionScannersObserveCreateBody.shape
)

const visionScannersScanSession = (): ToolBase<
    typeof VisionScannersScanSessionSchema,
    Schemas.ObserveAlreadyScanned
> => ({
    name: 'vision-scanners-scan-session',
    schema: VisionScannersScanSessionSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersScanSessionSchema>) => {
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

const VisionScannersUpdateSchema = VisionScannersPartialUpdateParams.omit({ project_id: true }).extend(
    VisionScannersPartialUpdateBody.shape
)

const visionScannersUpdate = (): ToolBase<typeof VisionScannersUpdateSchema, Schemas.ReplayScanner> => ({
    name: 'vision-scanners-update',
    schema: VisionScannersUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersUpdateSchema>) => {
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
