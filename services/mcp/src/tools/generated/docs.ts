// AUTO-GENERATED from services/mcp/definitions/docs.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { DocsSearchBody } from '@/generated/docs/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DocsSearchSchema = DocsSearchBody

const docsSearch = (): ToolBase<typeof DocsSearchSchema, Schemas.DocsSearchResponse> => ({
    name: 'docs-search',
    schema: DocsSearchSchema,
    handler: async (context: Context, params: z.infer<typeof DocsSearchSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.DocsSearchResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_tools/docs_search/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'docs-search': docsSearch,
}
