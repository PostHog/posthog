// AUTO-GENERATED from products/cdp/mcp/function_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionTemplatesListQueryParams,
    HogFunctionTemplatesRetrieveParams,
} from '@/generated/function_templates/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FunctionTemplatesListSchema = HogFunctionTemplatesListQueryParams

const functionTemplatesList = (): ToolBase<
    typeof FunctionTemplatesListSchema,
    Schemas.PaginatedHogFunctionTemplateList & { _posthogUrl: string }
> => ({
    name: 'function-templates-list',
    schema: FunctionTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionTemplatesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionTemplateList>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_function_templates/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                template_id: params.template_id,
                type: params.type,
                types: params.types,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/pipeline/templates`,
        }
    },
})

const FunctionTemplatesRetrieveSchema = HogFunctionTemplatesRetrieveParams.omit({ project_id: true })

const functionTemplatesRetrieve = (): ToolBase<
    typeof FunctionTemplatesRetrieveSchema,
    Schemas.HogFunctionTemplate
> => ({
    name: 'function-templates-retrieve',
    schema: FunctionTemplatesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FunctionTemplatesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunctionTemplate>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_function_templates/${params.template_id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'function-templates-list': functionTemplatesList,
    'function-templates-retrieve': functionTemplatesRetrieve,
}
