// AUTO-GENERATED from products/business_knowledge/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    BusinessKnowledgeDocumentsWindowListParams,
    BusinessKnowledgeDocumentsWindowListQueryParams,
} from '@/generated/business_knowledge/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BusinessKnowledgeDocumentWindowRetrieveSchema = BusinessKnowledgeDocumentsWindowListParams.omit({
    project_id: true,
}).extend(BusinessKnowledgeDocumentsWindowListQueryParams.shape)

const businessKnowledgeDocumentWindowRetrieve = (): ToolBase<
    typeof BusinessKnowledgeDocumentWindowRetrieveSchema,
    Schemas.KnowledgeDocumentWindow[]
> => ({
    name: 'business-knowledge-document-window-retrieve',
    schema: BusinessKnowledgeDocumentWindowRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof BusinessKnowledgeDocumentWindowRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.KnowledgeDocumentWindow[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/business_knowledge/documents/${encodeURIComponent(String(params.id))}/window/`,
            query: {
                around_ordinal: params.around_ordinal,
                radius: params.radius,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'business-knowledge-document-window-retrieve': businessKnowledgeDocumentWindowRetrieve,
}
