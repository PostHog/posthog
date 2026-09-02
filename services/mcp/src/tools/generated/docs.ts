// AUTO-GENERATED from products/docs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { DocsDataPointsSubmitCreateBody, DocsSearchBody } from '@/generated/docs/api'
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_tools/docs_search/`,
            body,
        })
        return result
    },
})

const DocDataPointSubmitSchema = DocsDataPointsSubmitCreateBody.extend({
    request_id: DocsDataPointsSubmitCreateBody.shape['request_id'].describe(
        'The request id given in the task description. Copy it exactly.'
    ),
    query: DocsDataPointsSubmitCreateBody.shape['query'].describe(
        'One HogQL SELECT (or WITH … SELECT) that returns exactly one row and one column. No semicolon, no other statements.'
    ),
    label: DocsDataPointsSubmitCreateBody.shape['label'].describe(
        'What the number measures, in a few words, as the reader will see it. For example "teams with replay on this month".'
    ),
    note: DocsDataPointsSubmitCreateBody.shape['note'].describe(
        'One short line for the reader when the number needs a caveat, or why there is no answer when status is none. Leave empty otherwise.'
    ),
})

const docDataPointSubmit = (): ToolBase<typeof DocDataPointSubmitSchema, Schemas.DataPointSubmitResult> => ({
    name: 'doc-data-point-submit',
    schema: DocDataPointSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof DocDataPointSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.label !== undefined) {
            body['label'] = params.label
        }
        if (params.note !== undefined) {
            body['note'] = params.note
        }
        const result = await context.api.request<Schemas.DataPointSubmitResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/docs/data_points/submit/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'docs-search': docsSearch,
    'doc-data-point-submit': docDataPointSubmit,
}
