// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisionScannersCreateBody,
    VisionScannersDestroyParams,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/`,
            query: {
                emits_signals: params.emits_signals,
                enabled: params.enabled,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                scanner_type: params.scanner_type,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/${encodeURIComponent(String(params.id))}/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.scanner_id))}/observations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                session_id: params.session_id,
                status: params.status,
                triggered_by: params.triggered_by,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/observe/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/vision/scanners/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'vision-scanners-create': visionScannersCreate,
    'vision-scanners-delete': visionScannersDelete,
    'vision-scanners-get': visionScannersGet,
    'vision-scanners-list': visionScannersList,
    'vision-scanners-observations-get': visionScannersObservationsGet,
    'vision-scanners-observations-list': visionScannersObservationsList,
    'vision-scanners-scan-session': visionScannersScanSession,
    'vision-scanners-update': visionScannersUpdate,
}
