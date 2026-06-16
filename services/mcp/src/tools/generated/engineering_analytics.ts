// AUTO-GENERATED from products/engineering_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EngineeringAnalyticsPrLifecycleQueryParams,
    EngineeringAnalyticsPullRequestsQueryParams,
    EngineeringAnalyticsWorkflowHealthQueryParams,
} from '@/generated/engineering_analytics/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PrLifecycleSchema = EngineeringAnalyticsPrLifecycleQueryParams.extend({
    pr_number: EngineeringAnalyticsPrLifecycleQueryParams.shape['pr_number'].describe(
        'Pull request number to inspect.'
    ),
    repo: EngineeringAnalyticsPrLifecycleQueryParams.shape['repo'].describe(
        "Optional 'owner/name' repository to disambiguate when the PR number exists in more than one connected repo."
    ),
})

const prLifecycle = (): ToolBase<typeof PrLifecycleSchema, Schemas.PRLifecycle> => ({
    name: 'pr-lifecycle',
    schema: PrLifecycleSchema,
    handler: async (context: Context, params: z.infer<typeof PrLifecycleSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PRLifecycle>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/pr_lifecycle/`,
            query: {
                pr_number: params.pr_number,
                repo: params.repo,
            },
        })
        return result
    },
})

const PullRequestsSchema = EngineeringAnalyticsPullRequestsQueryParams.extend({
    date_from: EngineeringAnalyticsPullRequestsQueryParams.shape['date_from'].describe(
        "Recency floor for merged/closed PRs — relative ('-30d', '-8w') or ISO8601. Open PRs are always included regardless of age. Defaults to -30d."
    ),
})

const pullRequests = (): ToolBase<typeof PullRequestsSchema, WithPostHogUrl<Schemas.PullRequestList>> => ({
    name: 'pull-requests',
    schema: PullRequestsSchema,
    handler: async (context: Context, params: z.infer<typeof PullRequestsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PullRequestList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/pull_requests/`,
            query: {
                date_from: params.date_from,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const WorkflowHealthSchema = EngineeringAnalyticsWorkflowHealthQueryParams.extend({
    date_from: EngineeringAnalyticsWorkflowHealthQueryParams.shape['date_from'].describe(
        "Window start — relative ('-30d', '-8w') or ISO8601. Defaults to -30d."
    ),
    date_to: EngineeringAnalyticsWorkflowHealthQueryParams.shape['date_to'].describe(
        'Window end — relative or ISO8601. Defaults to now.'
    ),
})

const workflowHealth = (): ToolBase<typeof WorkflowHealthSchema, WithPostHogUrl<Schemas.WorkflowHealthItem[]>> => ({
    name: 'workflow-health',
    schema: WorkflowHealthSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowHealthSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WorkflowHealthItem[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/workflow_health/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics/workflows')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'pr-lifecycle': prLifecycle,
    'pull-requests': pullRequests,
    'workflow-health': workflowHealth,
}
