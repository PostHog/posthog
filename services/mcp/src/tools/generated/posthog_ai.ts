// AUTO-GENERATED from products/posthog_ai/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ConversationsListQueryParams, ConversationsRetrieveParams } from '@/generated/posthog_ai/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ConversationsListSchema = ConversationsListQueryParams

const conversationsList = (): ToolBase<
    typeof ConversationsListSchema,
    WithPostHogUrl<Schemas.PaginatedConversationMinimalList>
> => ({
    name: 'conversations-list',
    schema: ConversationsListSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedConversationMinimalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['id', 'title', 'topic', 'status', 'type', 'created_at', 'updated_at'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/')
    },
})

const ConversationsRetrieveSchema = ConversationsRetrieveParams.omit({ project_id: true })

const conversationsRetrieve = (): ToolBase<typeof ConversationsRetrieveSchema, Schemas.Conversation> => ({
    name: 'conversations-retrieve',
    schema: ConversationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Conversation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/${encodeURIComponent(String(params.conversation))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'conversations-list': conversationsList,
    'conversations-retrieve': conversationsRetrieve,
}
