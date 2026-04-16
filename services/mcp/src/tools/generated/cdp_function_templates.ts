// AUTO-GENERATED from products/cdp/mcp/cdp_function_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionTemplatesListQueryParams,
    HogFunctionTemplatesRetrieveParams,
} from '@/generated/cdp_function_templates/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CdpFunctionTemplatesListSchema = HogFunctionTemplatesListQueryParams

const cdpFunctionTemplatesList = (): ToolBase<
    typeof CdpFunctionTemplatesListSchema,
    WithPostHogUrl<Schemas.PaginatedHogFunctionTemplateList>
> => ({
    name: 'cdp-function-templates-list',
    schema: CdpFunctionTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionTemplatesListSchema>) => {
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
        return await withPostHogUrl(context, result, '/pipeline/templates')
    },
})

const CdpFunctionTemplatesRetrieveSchema = HogFunctionTemplatesRetrieveParams.omit({ project_id: true })

const cdpFunctionTemplatesRetrieve = (): ToolBase<
    typeof CdpFunctionTemplatesRetrieveSchema,
    Schemas.HogFunctionTemplate
> => ({
    name: 'cdp-function-templates-retrieve',
    schema: CdpFunctionTemplatesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionTemplatesRetrieveSchema>) => {
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
