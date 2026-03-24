import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

interface QueryWrapperConfig<T extends ZodObjectAny> {
    name: string
    schema: T
    kind: string
    uiResourceUri?: string
}

export function createQueryWrapper<T extends ZodObjectAny>(config: QueryWrapperConfig<T>): () => ToolBase<T> {
    return () => ({
        name: config.name,
        schema: config.schema,
        handler: async (context: Context, params: z.infer<T>) => {
            const projectId = await context.stateManager.getProjectId()
            const query = { ...params, kind: config.kind }
            const result = await context.api.request<{
                results: unknown
                columns?: unknown
                formatted_results?: string
            }>({
                method: 'POST',
                path: `/api/environments/${projectId}/query/`,
                body: { query },
                headers: { 'X-PostHog-Client': 'mcp' },
            })
            const queryParam = encodeURIComponent(JSON.stringify(query))
            const baseUrl = context.api.getProjectBaseUrl(projectId)
            return {
                results: result.formatted_results ?? result.results,
                _posthogUrl: `${baseUrl}/insights/new?q=${queryParam}`,
            }
        },
        ...(config.uiResourceUri ? { _meta: { ui: { resourceUri: config.uiResourceUri } } } : {}),
    })
}
