// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisionObservationsListQueryParams,
    VisionObservationsRetrieveParams,
    VisionScannersCreateBody,
    VisionScannersDestroyParams,
    VisionScannersEstimateCreateBody,
    VisionScannersListQueryParams,
    VisionScannersObservationsListParams,
    VisionScannersObservationsListQueryParams,
    VisionScannersObservationsRetrieveParams,
    VisionScannersObserveCreateBody,
    VisionScannersObserveCreateParams,
    VisionScannersPartialUpdateBody,
    VisionScannersPartialUpdateParams,
    VisionScannersRetrieveParams,
} from '@/generated/replay_vision/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisionObservationsListSchema = VisionObservationsListQueryParams

const visionObservationsList = (): ToolBase<
    typeof VisionObservationsListSchema,
    WithPostHogUrl<Schemas.PaginatedReplayObservationList>
> => ({
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
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionObservationsRetrieveSchema = VisionObservationsRetrieveParams.omit({ project_id: true })

const visionObservationsRetrieve = (): ToolBase<
    typeof VisionObservationsRetrieveSchema,
    Schemas.ReplayObservation
> => ({
    name: 'vision-observations-retrieve',
    schema: VisionObservationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisionObservationsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayObservation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/observations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
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
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                scanner_type: params.scanner_type,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionScannersObservationsGetSchema = VisionScannersObservationsRetrieveParams.omit({ project_id: true })

const visionScannersObservationsGet = (): ToolBase<
    typeof VisionScannersObservationsGetSchema,
    Schemas.ReplayObservation
> => ({
    name: 'vision-scanners-observations-get',
    schema: VisionScannersObservationsGetSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersObservationsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReplayObservation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisionScannersObservationsListSchema = VisionScannersObservationsListParams.omit({ project_id: true }).extend(
    VisionScannersObservationsListQueryParams.shape
)

const visionScannersObservationsList = (): ToolBase<
    typeof VisionScannersObservationsListSchema,
    WithPostHogUrl<Schemas.PaginatedReplayObservationList>
> => ({
    name: 'vision-scanners-observations-list',
    schema: VisionScannersObservationsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersObservationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReplayObservationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/`,
            query: {
                labeled: params.labeled,
                limit: params.limit,
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
        return await withPostHogUrl(context, result, '/replay-vision')
    },
})

const VisionScannersScanSessionSchema = VisionScannersObserveCreateParams.omit({ project_id: true }).extend(
    VisionScannersObserveCreateBody.shape
)

const visionScannersScanSession = (): ToolBase<typeof VisionScannersScanSessionSchema, unknown> => ({
    name: 'vision-scanners-scan-session',
    schema: VisionScannersScanSessionSchema,
    handler: async (context: Context, params: z.infer<typeof VisionScannersScanSessionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.session_id !== undefined) {
            body['session_id'] = params.session_id
        }
        const result = await context.api.request<unknown>({
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
        const result = await context.api.request<Schemas.ReplayScanner>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'vision-observations-list': visionObservationsList,
    'vision-observations-retrieve': visionObservationsRetrieve,
    'vision-quota-retrieve': visionQuotaRetrieve,
    'vision-scanners-create': visionScannersCreate,
    'vision-scanners-delete': visionScannersDelete,
    'vision-scanners-estimate-create': visionScannersEstimateCreate,
    'vision-scanners-get': visionScannersGet,
    'vision-scanners-list': visionScannersList,
    'vision-scanners-observations-get': visionScannersObservationsGet,
    'vision-scanners-observations-list': visionScannersObservationsList,
    'vision-scanners-scan-session': visionScannersScanSession,
    'vision-scanners-update': visionScannersUpdate,
}
