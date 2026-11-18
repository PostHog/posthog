// AUTO-GENERATED from services/mcp/definitions/docs.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/docs/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DocsSearchSchema = () => {
    const DocsSearchBody = orvalSchemas.DocsSearchBody()
    return DocsSearchBody
}

const docsSearch = (): ToolBase<ReturnType<typeof DocsSearchSchema>, Schemas.DocsSearchResponse> => ({
    name: 'docs-search',
    schema: DocsSearchSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DocsSearchSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.DocsSearchResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_tools/docs_search/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'docs-search': docsSearch,
}
