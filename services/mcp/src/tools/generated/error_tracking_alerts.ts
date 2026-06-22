// AUTO-GENERATED from products/error_tracking/mcp/error_tracking_alerts.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionsCreateBody,
    HogFunctionsDestroyParams,
    HogFunctionsListQueryParams,
    HogFunctionsPartialUpdateBody,
    HogFunctionsPartialUpdateParams,
} from '@/generated/error_tracking_alerts/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ErrorTrackingAlertsCreateSchema = HogFunctionsCreateBody.extend({
    type: HogFunctionsCreateBody.shape['type'].describe(
        'Must be `internal_destination` for an error tracking alert. Other values create non-alert HogFunctions and should be created via `cdp-functions-create` instead.'
    ),
    template_id: HogFunctionsCreateBody.shape['template_id'].describe(
        'Integration template — one of `template-slack`, `template-webhook`, `template-discord`, `template-microsoft-teams`, `template-linear`, `template-github`, `template-gitlab`.'
    ),
    enabled: HogFunctionsCreateBody.shape['enabled'].describe('Whether the alert is active. Defaults to true.'),
})

const errorTrackingAlertsCreate = (): ToolBase<typeof ErrorTrackingAlertsCreateSchema, Schemas.HogFunction> => ({
    name: 'error-tracking-alerts-create',
    schema: ErrorTrackingAlertsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAlertsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/`,
            body,
        })
        return result
    },
})

const ErrorTrackingAlertsDeleteSchema = HogFunctionsDestroyParams.omit({ project_id: true })

const errorTrackingAlertsDelete = (): ToolBase<typeof ErrorTrackingAlertsDeleteSchema, Schemas.HogFunction> => ({
    name: 'error-tracking-alerts-delete',
    schema: ErrorTrackingAlertsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAlertsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const ErrorTrackingAlertsListSchema = HogFunctionsListQueryParams

const errorTrackingAlertsList = (): ToolBase<
    typeof ErrorTrackingAlertsListSchema,
    WithPostHogUrl<Schemas.PaginatedHogFunctionMinimalList>
> => ({
    name: 'error-tracking-alerts-list',
    schema: ErrorTrackingAlertsListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAlertsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionMinimalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/`,
            query: {
                created_at: params.created_at,
                created_by: params.created_by,
                enabled: params.enabled,
                id: params.id,
                limit: params.limit,
                offset: params.offset,
                type: Array.isArray(params.type) ? params.type.join(',') || undefined : params.type,
                updated_at: params.updated_at,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'type',
                    'name',
                    'description',
                    'enabled',
                    'icon_url',
                    'template.id',
                    'status',
                    'created_at',
                    'updated_at',
                    'created_by',
                    'filters',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/error_tracking')
    },
})

const ErrorTrackingAlertsPartialUpdateSchema = HogFunctionsPartialUpdateParams.omit({ project_id: true })
    .extend(HogFunctionsPartialUpdateBody.shape)
    .extend({
        enabled: HogFunctionsPartialUpdateBody.shape['enabled'].describe(
            'Set to true to activate the alert or false to silence it without deleting.'
        ),
    })

const errorTrackingAlertsPartialUpdate = (): ToolBase<
    typeof ErrorTrackingAlertsPartialUpdateSchema,
    Schemas.HogFunction
> => ({
    name: 'error-tracking-alerts-partial-update',
    schema: ErrorTrackingAlertsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAlertsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-alerts-create': errorTrackingAlertsCreate,
    'error-tracking-alerts-delete': errorTrackingAlertsDelete,
    'error-tracking-alerts-list': errorTrackingAlertsList,
    'error-tracking-alerts-partial-update': errorTrackingAlertsPartialUpdate,
}
