// AUTO-GENERATED from products/alerts_platform/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/alerts_platform/api'
import { WarehouseSyncAlertCreateSchema, WarehouseSyncAlertUpdateSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PlatformAlertsCreateSchema = () => WarehouseSyncAlertCreateSchema

const platformAlertsCreate = (): ToolBase<
    ReturnType<typeof PlatformAlertsCreateSchema>,
    Schemas.PlatformAlertConfiguration
> => ({
    name: 'platform-alerts-create',
    schema: PlatformAlertsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PlatformAlertsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = PlatformAlertsCreateSchema().parse(params)
        const result = await context.api.request<Schemas.PlatformAlertConfiguration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/platform_alerts/`,
            body: parsedParams,
        })
        return result
    },
})

const PlatformAlertsDestroySchema = () => {
    const PlatformAlertsDestroyParams = orvalSchemas.PlatformAlertsDestroyParams()
    return PlatformAlertsDestroyParams.omit({ project_id: true })
}

const platformAlertsDestroy = (): ToolBase<ReturnType<typeof PlatformAlertsDestroySchema>, unknown> => ({
    name: 'platform-alerts-destroy',
    schema: PlatformAlertsDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PlatformAlertsDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/platform_alerts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const PlatformAlertsListSchema = () => {
    const PlatformAlertsListQueryParams = orvalSchemas.PlatformAlertsListQueryParams()
    return PlatformAlertsListQueryParams
}

const platformAlertsList = (): ToolBase<
    ReturnType<typeof PlatformAlertsListSchema>,
    WithPostHogUrl<Schemas.PaginatedPlatformAlertConfigurationList>
> => ({
    name: 'platform-alerts-list',
    schema: PlatformAlertsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PlatformAlertsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedPlatformAlertConfigurationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/platform_alerts/`,
            query: {
                created_by: params.created_by,
                legacy_configuration_id: params.legacy_configuration_id,
                limit: params.limit,
                offset: params.offset,
                source_kind: params.source_kind,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'enabled',
                    'source_kind',
                    'source_config',
                    'grouping',
                    'cooldown_minutes',
                    'check_status',
                    'last_checked_at',
                    'last_error_message',
                    'destination_types',
                    'owner',
                    'alerts',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/data-management/sources')
    },
})

const PlatformAlertsPartialUpdateSchema = () => WarehouseSyncAlertUpdateSchema

const platformAlertsPartialUpdate = (): ToolBase<
    ReturnType<typeof PlatformAlertsPartialUpdateSchema>,
    Schemas.PlatformAlertConfiguration
> => ({
    name: 'platform-alerts-partial-update',
    schema: PlatformAlertsPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PlatformAlertsPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = PlatformAlertsPartialUpdateSchema().parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.PlatformAlertConfiguration>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/platform_alerts/${encodeURIComponent(String(id))}/`,
            body,
        })
        return result
    },
})

const PlatformAlertsRetrieveSchema = () => {
    const PlatformAlertsRetrieveParams = orvalSchemas.PlatformAlertsRetrieveParams()
    return PlatformAlertsRetrieveParams.omit({ project_id: true })
}

const platformAlertsRetrieve = (): ToolBase<
    ReturnType<typeof PlatformAlertsRetrieveSchema>,
    Schemas.PlatformAlertConfiguration
> => ({
    name: 'platform-alerts-retrieve',
    schema: PlatformAlertsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PlatformAlertsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PlatformAlertConfiguration>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/platform_alerts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'platform-alerts-create': platformAlertsCreate,
    'platform-alerts-destroy': platformAlertsDestroy,
    'platform-alerts-list': platformAlertsList,
    'platform-alerts-partial-update': platformAlertsPartialUpdate,
    'platform-alerts-retrieve': platformAlertsRetrieve,
}
