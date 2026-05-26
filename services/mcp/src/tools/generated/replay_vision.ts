// AUTO-GENERATED from products/replay_vision/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisionScannersListQueryParams,
    VisionScannersObservationsListParams,
    VisionScannersObservationsListQueryParams,
    VisionScannersObservationsRetrieveParams,
    VisionScannersObserveCreateBody,
    VisionScannersObserveCreateParams,
    VisionScannersRetrieveParams,
} from '@/generated/replay_vision/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'vision-scanners-get': visionScannersGet,
    'vision-scanners-list': visionScannersList,
    'vision-scanners-observations-get': visionScannersObservationsGet,
    'vision-scanners-observations-list': visionScannersObservationsList,
    'vision-scanners-scan-session': visionScannersScanSession,
}
