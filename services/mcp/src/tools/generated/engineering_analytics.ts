// AUTO-GENERATED from products/engineering_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    EngineeringAnalyticsPrLifecycleQueryParams,
    EngineeringAnalyticsTimeToMergeQueryParams,
    EngineeringAnalyticsWorkflowReportQueryParams,
} from '@/generated/engineering_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowReportSchema = EngineeringAnalyticsWorkflowReportQueryParams.extend({
    date_from: EngineeringAnalyticsWorkflowReportQueryParams.shape['date_from'].describe(
        "Start of the window — a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'."
    ),
    date_to: EngineeringAnalyticsWorkflowReportQueryParams.shape['date_to'].describe(
        "End of the window — a relative string or ISO8601 timestamp. Omit for 'now'."
    ),
    repo: EngineeringAnalyticsWorkflowReportQueryParams.shape['repo'].describe(
        "Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows."
    ),
})

const workflowReport = (): ToolBase<typeof WorkflowReportSchema, Schemas.WorkflowReport> => ({
    name: 'workflow-report',
    schema: WorkflowReportSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowReportSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WorkflowReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/workflow_report/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                repo: params.repo,
            },
        })
        return result
    },
})

const TimeToMergeSchema = EngineeringAnalyticsTimeToMergeQueryParams.extend({
    date_from: EngineeringAnalyticsTimeToMergeQueryParams.shape['date_from'].describe(
        "Start of the window — a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'."
    ),
    date_to: EngineeringAnalyticsTimeToMergeQueryParams.shape['date_to'].describe(
        "End of the window — a relative string or ISO8601 timestamp. Omit for 'now'."
    ),
    repo: EngineeringAnalyticsTimeToMergeQueryParams.shape['repo'].describe(
        "Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows."
    ),
    group_by_author: EngineeringAnalyticsTimeToMergeQueryParams.shape['group_by_author'].describe(
        'Set true to split results per author handle instead of one overall bucket.'
    ),
})

const timeToMerge = (): ToolBase<typeof TimeToMergeSchema, Schemas.TimeToMerge> => ({
    name: 'time-to-merge',
    schema: TimeToMergeSchema,
    handler: async (context: Context, params: z.infer<typeof TimeToMergeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TimeToMerge>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/time_to_merge/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                group_by_author: params.group_by_author,
                repo: params.repo,
            },
        })
        return result
    },
})

const PrLifecycleSchema = EngineeringAnalyticsPrLifecycleQueryParams.extend({
    pr_number: EngineeringAnalyticsPrLifecycleQueryParams.shape['pr_number'].describe(
        'Pull request number to inspect.'
    ),
    repo: EngineeringAnalyticsPrLifecycleQueryParams.shape['repo'].describe(
        "Optional 'owner/name' repository. In v1 this only labels the response."
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflow-report': workflowReport,
    'time-to-merge': timeToMerge,
    'pr-lifecycle': prLifecycle,
}
