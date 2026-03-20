// AUTO-GENERATED from products/alerts/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AlertsCreateBody,
    AlertsDestroyParams,
    AlertsListQueryParams,
    AlertsPartialUpdateBody,
    AlertsPartialUpdateParams,
    AlertsRetrieveParams,
    AlertsSimulateCreateBody,
} from '@/generated/alerts/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AlertsListSchema = AlertsListQueryParams

const alertsList = (): ToolBase<typeof AlertsListSchema, Schemas.PaginatedAlertList & { _posthogUrl: string }> => ({
    name: 'alerts-list',
    schema: AlertsListSchema,
    handler: async (context: Context, params: z.infer<typeof AlertsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAlertList>({
            method: 'GET',
            path: `/api/projects/${projectId}/alerts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/insights`,
        }
    },
})

const AlertGetSchema = AlertsRetrieveParams.omit({ project_id: true })

const alertGet = (): ToolBase<typeof AlertGetSchema, Schemas.Alert> => ({
    name: 'alert-get',
    schema: AlertGetSchema,
    handler: async (context: Context, params: z.infer<typeof AlertGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Alert>({
            method: 'GET',
            path: `/api/projects/${projectId}/alerts/${params.id}/`,
        })
        return result
    },
})

const AlertCreateSchema = AlertsCreateBody

const alertCreate = (): ToolBase<typeof AlertCreateSchema, Schemas.Alert> => ({
    name: 'alert-create',
    schema: AlertCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AlertCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.subscribed_users !== undefined) {
            body['subscribed_users'] = params.subscribed_users
        }
        if (params.threshold !== undefined) {
            body['threshold'] = params.threshold
        }
        if (params.condition !== undefined) {
            body['condition'] = params.condition
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.detector_config !== undefined) {
            body['detector_config'] = params.detector_config
        }
        if (params.calculation_interval !== undefined) {
            body['calculation_interval'] = params.calculation_interval
        }
        if (params.snoozed_until !== undefined) {
            body['snoozed_until'] = params.snoozed_until
        }
        if (params.skip_weekend !== undefined) {
            body['skip_weekend'] = params.skip_weekend
        }
        const result = await context.api.request<Schemas.Alert>({
            method: 'POST',
            path: `/api/projects/${projectId}/alerts/`,
            body,
        })
        return result
    },
})

const AlertUpdateSchema = AlertsPartialUpdateParams.omit({ project_id: true }).extend(AlertsPartialUpdateBody.shape)

const alertUpdate = (): ToolBase<typeof AlertUpdateSchema, Schemas.Alert> => ({
    name: 'alert-update',
    schema: AlertUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AlertUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.subscribed_users !== undefined) {
            body['subscribed_users'] = params.subscribed_users
        }
        if (params.threshold !== undefined) {
            body['threshold'] = params.threshold
        }
        if (params.condition !== undefined) {
            body['condition'] = params.condition
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.detector_config !== undefined) {
            body['detector_config'] = params.detector_config
        }
        if (params.calculation_interval !== undefined) {
            body['calculation_interval'] = params.calculation_interval
        }
        if (params.snoozed_until !== undefined) {
            body['snoozed_until'] = params.snoozed_until
        }
        if (params.skip_weekend !== undefined) {
            body['skip_weekend'] = params.skip_weekend
        }
        const result = await context.api.request<Schemas.Alert>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/alerts/${params.id}/`,
            body,
        })
        return result
    },
})

const AlertDeleteSchema = AlertsDestroyParams.omit({ project_id: true })

const alertDelete = (): ToolBase<typeof AlertDeleteSchema, unknown> => ({
    name: 'alert-delete',
    schema: AlertDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof AlertDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${projectId}/alerts/${params.id}/`,
        })
        return result
    },
})

const AlertSimulateSchema = AlertsSimulateCreateBody

const alertSimulate = (): ToolBase<typeof AlertSimulateSchema, Schemas.AlertSimulateResponse> => ({
    name: 'alert-simulate',
    schema: AlertSimulateSchema,
    handler: async (context: Context, params: z.infer<typeof AlertSimulateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.detector_config !== undefined) {
            body['detector_config'] = params.detector_config
        }
        if (params.series_index !== undefined) {
            body['series_index'] = params.series_index
        }
        if (params.date_from !== undefined) {
            body['date_from'] = params.date_from
        }
        const result = await context.api.request<Schemas.AlertSimulateResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/alerts/simulate/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'alerts-list': alertsList,
    'alert-get': alertGet,
    'alert-create': alertCreate,
    'alert-update': alertUpdate,
    'alert-delete': alertDelete,
    'alert-simulate': alertSimulate,
}
