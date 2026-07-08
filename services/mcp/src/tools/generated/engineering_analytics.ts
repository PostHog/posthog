// AUTO-GENERATED from products/engineering_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EngineeringAnalyticsCiFailureLogsQueryParams,
    EngineeringAnalyticsFlakyTestsQueryParams,
    EngineeringAnalyticsPrCostQueryParams,
    EngineeringAnalyticsPrLifecycleQueryParams,
    EngineeringAnalyticsPullRequestsQueryParams,
    EngineeringAnalyticsWorkflowHealthQueryParams,
    EngineeringAnalyticsWorkflowJobsQueryParams,
    EngineeringAnalyticsWorkflowRunnerCostsQueryParams,
} from '@/generated/engineering_analytics/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const EngineeringAnalyticsCiFailureLogsSchema = EngineeringAnalyticsCiFailureLogsQueryParams

const engineeringAnalyticsCiFailureLogs = (): ToolBase<
    typeof EngineeringAnalyticsCiFailureLogsSchema,
    Schemas.CIFailureLogs
> => ({
    name: 'engineering-analytics-ci-failure-logs',
    schema: EngineeringAnalyticsCiFailureLogsSchema,
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsCiFailureLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CIFailureLogs>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/ci_failure_logs/`,
            query: {
                pr_number: params.pr_number,
                repo: params.repo,
                source_id: params.source_id,
            },
        })
        return result
    },
})

const EngineeringAnalyticsFlakyTestsSchema = EngineeringAnalyticsFlakyTestsQueryParams

const engineeringAnalyticsFlakyTests = (): ToolBase<
    typeof EngineeringAnalyticsFlakyTestsSchema,
    WithPostHogUrl<Schemas.FlakyTestList>
> => ({
    name: 'engineering-analytics-flaky-tests',
    schema: EngineeringAnalyticsFlakyTestsSchema,
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsFlakyTestsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FlakyTestList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/flaky_tests/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                min_failed_prs: params.min_failed_prs,
                min_rerun_passes: params.min_rerun_passes,
                source_id: params.source_id,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const EngineeringAnalyticsPrCostSchema = EngineeringAnalyticsPrCostQueryParams

const engineeringAnalyticsPrCost = (): ToolBase<typeof EngineeringAnalyticsPrCostSchema, Schemas.PRCostSummary> => ({
    name: 'engineering-analytics-pr-cost',
    schema: EngineeringAnalyticsPrCostSchema,
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsPrCostSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PRCostSummary>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/pr_cost/`,
            query: {
                pr_number: params.pr_number,
                repo: params.repo,
                source_id: params.source_id,
            },
        })
        return result
    },
})

const EngineeringAnalyticsSourcesSchema = z.object({})

const engineeringAnalyticsSources = (): ToolBase<
    typeof EngineeringAnalyticsSourcesSchema,
    WithPostHogUrl<Schemas.GitHubSource[]>
> => ({
    name: 'engineering-analytics-sources',
    schema: EngineeringAnalyticsSourcesSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsSourcesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GitHubSource[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/sources/`,
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const EngineeringAnalyticsWorkflowJobsSchema = EngineeringAnalyticsWorkflowJobsQueryParams

const engineeringAnalyticsWorkflowJobs = (): ToolBase<
    typeof EngineeringAnalyticsWorkflowJobsSchema,
    WithPostHogUrl<Schemas.WorkflowJob[]>
> => ({
    name: 'engineering-analytics-workflow-jobs',
    schema: EngineeringAnalyticsWorkflowJobsSchema,
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsWorkflowJobsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WorkflowJob[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/workflow_jobs/`,
            query: {
                run_attempt: params.run_attempt,
                run_id: params.run_id,
                source_id: params.source_id,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const EngineeringAnalyticsWorkflowRunnerCostsSchema = EngineeringAnalyticsWorkflowRunnerCostsQueryParams

const engineeringAnalyticsWorkflowRunnerCosts = (): ToolBase<
    typeof EngineeringAnalyticsWorkflowRunnerCostsSchema,
    WithPostHogUrl<Schemas.WorkflowRunnerCost[]>
> => ({
    name: 'engineering-analytics-workflow-runner-costs',
    schema: EngineeringAnalyticsWorkflowRunnerCostsSchema,
    handler: async (context: Context, params: z.infer<typeof EngineeringAnalyticsWorkflowRunnerCostsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WorkflowRunnerCost[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/workflow_runner_costs/`,
            query: {
                branch: params.branch,
                date_from: params.date_from,
                date_to: params.date_to,
                repo: params.repo,
                source_id: params.source_id,
                workflow_name: params.workflow_name,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const PrLifecycleSchema = EngineeringAnalyticsPrLifecycleQueryParams

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
                source_id: params.source_id,
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
                author: params.author,
                date_from: params.date_from,
                source_id: params.source_id,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics')
    },
})

const WorkflowHealthSchema = EngineeringAnalyticsWorkflowHealthQueryParams.extend({
    date_from: EngineeringAnalyticsWorkflowHealthQueryParams.shape['date_from'].describe(
        "Window start — relative ('-24h', '-7d') or ISO8601. Defaults to -24h."
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
                branch: params.branch,
                date_from: params.date_from,
                date_to: params.date_to,
                source_id: params.source_id,
            },
        })
        return await withPostHogUrl(context, result, '/engineering-analytics/workflows')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'engineering-analytics-ci-failure-logs': engineeringAnalyticsCiFailureLogs,
    'engineering-analytics-flaky-tests': engineeringAnalyticsFlakyTests,
    'engineering-analytics-pr-cost': engineeringAnalyticsPrCost,
    'engineering-analytics-sources': engineeringAnalyticsSources,
    'engineering-analytics-workflow-jobs': engineeringAnalyticsWorkflowJobs,
    'engineering-analytics-workflow-runner-costs': engineeringAnalyticsWorkflowRunnerCosts,
    'pr-lifecycle': prLifecycle,
    'pull-requests': pullRequests,
    'workflow-health': workflowHealth,
}
