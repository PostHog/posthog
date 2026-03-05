// AUTO-GENERATED from products/cdp/mcp/hog_function_templates.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionTemplatesListQueryParams,
    HogFunctionTemplatesRetrieveParams,
} from '@/generated/hog_function_templates/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HogFunctionTemplatesListSchema = HogFunctionTemplatesListQueryParams

const hogFunctionTemplatesList = (): ToolBase<
    typeof HogFunctionTemplatesListSchema,
    Schemas.PaginatedHogFunctionTemplateList & { _posthogUrl: string }
> => ({
    name: 'hog-function-templates-list',
    schema: HogFunctionTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionTemplatesListSchema>) => {
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
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cdp`,
        }
    },
})

const HogFunctionTemplatesRetrieveSchema = HogFunctionTemplatesRetrieveParams.omit({ project_id: true })

const hogFunctionTemplatesRetrieve = (): ToolBase<
    typeof HogFunctionTemplatesRetrieveSchema,
    Schemas.HogFunctionTemplate
> => ({
    name: 'hog-function-templates-retrieve',
    schema: HogFunctionTemplatesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFunctionTemplatesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunctionTemplate>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_function_templates/${params.template_id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'hog-function-templates-list': hogFunctionTemplatesList,
    'hog-function-templates-retrieve': hogFunctionTemplatesRetrieve,
}
