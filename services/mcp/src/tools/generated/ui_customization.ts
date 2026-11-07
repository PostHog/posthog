// AUTO-GENERATED from products/ui_customization/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/ui_customization/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UiCustomizationGetSchema = () => {
    const UiCustomizationRetrieveParams = orvalSchemas.UiCustomizationRetrieveParams()
    return UiCustomizationRetrieveParams.omit({ project_id: true })
}

const uiCustomizationGet = (): ToolBase<ReturnType<typeof UiCustomizationGetSchema>, Schemas.Customization> => ({
    name: 'ui-customization-get',
    schema: UiCustomizationGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UiCustomizationGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Customization>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/${encodeURIComponent(String(params.context))}/`,
        })
        return result
    },
})

const UiCustomizationResetSchema = () => {
    const UiCustomizationDestroyParams = orvalSchemas.UiCustomizationDestroyParams()
    return UiCustomizationDestroyParams.omit({ project_id: true })
}

const uiCustomizationReset = (): ToolBase<ReturnType<typeof UiCustomizationResetSchema>, Schemas.Customization> => ({
    name: 'ui-customization-reset',
    schema: UiCustomizationResetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UiCustomizationResetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Customization>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/${encodeURIComponent(String(params.context))}/`,
        })
        return result
    },
})

const UiCustomizationSetSchema = () => {
    const UiCustomizationUpdateBody = orvalSchemas.UiCustomizationUpdateBody()
    const UiCustomizationUpdateParams = orvalSchemas.UiCustomizationUpdateParams()
    return UiCustomizationUpdateParams.omit({ project_id: true }).extend(UiCustomizationUpdateBody.shape)
}

const uiCustomizationSet = (): ToolBase<ReturnType<typeof UiCustomizationSetSchema>, Schemas.Customization> => ({
    name: 'ui-customization-set',
    schema: UiCustomizationSetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UiCustomizationSetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.layout !== undefined) {
            body['layout'] = params.layout
        }
        const result = await context.api.request<Schemas.Customization>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/ui_customization/${encodeURIComponent(String(params.context))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'ui-customization-get': uiCustomizationGet,
    'ui-customization-reset': uiCustomizationReset,
    'ui-customization-set': uiCustomizationSet,
}
