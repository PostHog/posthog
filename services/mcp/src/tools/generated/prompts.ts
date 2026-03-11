// AUTO-GENERATED from products/llm_analytics/mcp/prompts.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmPromptsCreateBody,
    LlmPromptsListQueryParams,
    LlmPromptsNamePartialUpdateBody,
    LlmPromptsNamePartialUpdateParams,
    LlmPromptsNameRetrieveParams,
    LlmPromptsNameRetrieveQueryParams,
} from '@/generated/prompts/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PromptListSchema = LlmPromptsListQueryParams.omit({ limit: true, offset: true })

const promptList = (): ToolBase<typeof PromptListSchema, Schemas.PaginatedLLMPromptList> => ({
    name: 'prompt-list',
    schema: PromptListSchema,
    handler: async (context: Context, params: z.infer<typeof PromptListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMPromptList>({
            method: 'GET',
            path: `/api/environments/${projectId}/llm_prompts/`,
            query: {
                search: params.search,
            },
        })
        return result
    },
})

const PromptGetSchema = LlmPromptsNameRetrieveParams.omit({ project_id: true }).extend(
    LlmPromptsNameRetrieveQueryParams.shape
)

const promptGet = (): ToolBase<typeof PromptGetSchema, Schemas.LLMPromptPublic> => ({
    name: 'prompt-get',
    schema: PromptGetSchema,
    handler: async (context: Context, params: z.infer<typeof PromptGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMPromptPublic>({
            method: 'GET',
            path: `/api/environments/${projectId}/llm_prompts/name/${params.prompt_name}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const PromptCreateSchema = LlmPromptsCreateBody

const promptCreate = (): ToolBase<typeof PromptCreateSchema, Schemas.LLMPrompt> => ({
    name: 'prompt-create',
    schema: PromptCreateSchema,
    handler: async (context: Context, params: z.infer<typeof PromptCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'POST',
            path: `/api/environments/${projectId}/llm_prompts/`,
            body,
        })
        return result
    },
})

const PromptUpdateSchema = LlmPromptsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmPromptsNamePartialUpdateBody.shape
)

const promptUpdate = (): ToolBase<typeof PromptUpdateSchema, Schemas.LLMPrompt> => ({
    name: 'prompt-update',
    schema: PromptUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof PromptUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMPrompt>({
            method: 'PATCH',
            path: `/api/environments/${projectId}/llm_prompts/name/${params.prompt_name}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'prompt-list': promptList,
    'prompt-get': promptGet,
    'prompt-create': promptCreate,
    'prompt-update': promptUpdate,
}
