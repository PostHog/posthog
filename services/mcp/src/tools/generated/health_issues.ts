// AUTO-GENERATED from services/mcp/definitions/health_issues.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/health_issues/api'
import { normalizeParamAliases } from '@/tools/cast-helpers'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HealthIssuesGetSchema = () => {
    const HealthIssuesRetrieveParams = orvalSchemas.HealthIssuesRetrieveParams()
    return z.preprocess(
        normalizeParamAliases({ id: ['issue_id', 'issueId', 'health_issue_id', 'healthIssueId'] }),
        HealthIssuesRetrieveParams.omit({ project_id: true }).extend({
            id: HealthIssuesRetrieveParams.shape['id'].describe(
                'The health issue\'s UUID, as returned in the `id` field of each health-issues-list result. Example call: `{"id": "018f3c2a-7b1e-7000-9c4d-5e6f7a8b9c0d"}`.'
            ),
        })
    )
}

const healthIssuesGet = (): ToolBase<ReturnType<typeof HealthIssuesGetSchema>, Schemas.HealthIssueDetail> => ({
    name: 'health-issues-get',
    schema: HealthIssuesGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HealthIssuesGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HealthIssueDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/health_issues/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const HealthIssuesListSchema = () => {
    const HealthIssuesListQueryParams = orvalSchemas.HealthIssuesListQueryParams()
    return HealthIssuesListQueryParams
}

const healthIssuesList = (): ToolBase<
    ReturnType<typeof HealthIssuesListSchema>,
    WithPostHogUrl<Schemas.PaginatedHealthIssueList>
> => ({
    name: 'health-issues-list',
    schema: HealthIssuesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HealthIssuesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHealthIssueList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/health_issues/`,
            query: {
                dismissed: params.dismissed,
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
                severity: params.severity,
                status: params.status,
            },
        })
        return await withPostHogUrl(context, result, '/health')
    },
})

const HealthIssuesSummarySchema = () => z.object({})

const healthIssuesSummary = (): ToolBase<ReturnType<typeof HealthIssuesSummarySchema>, Schemas.HealthIssueSummary> => ({
    name: 'health-issues-summary',
    schema: HealthIssuesSummarySchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof HealthIssuesSummarySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HealthIssueSummary>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/health_issues/summary/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'health-issues-get': healthIssuesGet,
    'health-issues-list': healthIssuesList,
    'health-issues-summary': healthIssuesSummary,
}
