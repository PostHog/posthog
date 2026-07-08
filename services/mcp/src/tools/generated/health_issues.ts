// AUTO-GENERATED from services/mcp/definitions/health_issues.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { HealthIssuesListQueryParams, HealthIssuesRetrieveParams } from '@/generated/health_issues/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HealthIssuesGetSchema = HealthIssuesRetrieveParams.omit({ project_id: true })

const healthIssuesGet = (): ToolBase<typeof HealthIssuesGetSchema, Schemas.HealthIssueDetail> => ({
    name: 'health-issues-get',
    schema: HealthIssuesGetSchema,
    handler: async (context: Context, params: z.infer<typeof HealthIssuesGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HealthIssueDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/health_issues/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const HealthIssuesListSchema = HealthIssuesListQueryParams

const healthIssuesList = (): ToolBase<
    typeof HealthIssuesListSchema,
    WithPostHogUrl<Schemas.PaginatedHealthIssueList>
> => ({
    name: 'health-issues-list',
    schema: HealthIssuesListSchema,
    handler: async (context: Context, params: z.infer<typeof HealthIssuesListSchema>) => {
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

const HealthIssuesSummarySchema = z.object({})

const healthIssuesSummary = (): ToolBase<typeof HealthIssuesSummarySchema, Schemas.HealthIssueSummary> => ({
    name: 'health-issues-summary',
    schema: HealthIssuesSummarySchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof HealthIssuesSummarySchema>) => {
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
