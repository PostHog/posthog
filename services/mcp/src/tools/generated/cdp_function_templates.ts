// AUTO-GENERATED from products/cdp/mcp/cdp_function_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/cdp_function_templates/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CdpFunctionTemplatesListSchema = () => {
    const HogFunctionTemplatesListQueryParams = orvalSchemas.HogFunctionTemplatesListQueryParams()
    return HogFunctionTemplatesListQueryParams
}

const cdpFunctionTemplatesList = (): ToolBase<
    ReturnType<typeof CdpFunctionTemplatesListSchema>,
    WithPostHogUrl<Schemas.PaginatedHogFunctionTemplateList>
> => ({
    name: 'cdp-function-templates-list',
    schema: CdpFunctionTemplatesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CdpFunctionTemplatesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionTemplateList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_function_templates/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                template_id: params.template_id,
                type: params.type,
                types: params.types,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'description',
                    'type',
                    'status',
                    'category',
                    'free',
                    'icon_url',
                    'code_language',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/pipeline/new')
    },
})

const CdpFunctionTemplatesRetrieveSchema = () => {
    const HogFunctionTemplatesRetrieveParams = orvalSchemas.HogFunctionTemplatesRetrieveParams()
    return HogFunctionTemplatesRetrieveParams.omit({ project_id: true })
}

const cdpFunctionTemplatesRetrieve = (): ToolBase<
    ReturnType<typeof CdpFunctionTemplatesRetrieveSchema>,
    Schemas.HogFunctionTemplate
> => ({
    name: 'cdp-function-templates-retrieve',
    schema: CdpFunctionTemplatesRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CdpFunctionTemplatesRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunctionTemplate>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_function_templates/${encodeURIComponent(String(params.template_id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cdp-function-templates-list': cdpFunctionTemplatesList,
    'cdp-function-templates-retrieve': cdpFunctionTemplatesRetrieve,
}
