// AUTO-GENERATED from products/workflows/mcp/transactional_email_log.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/transactional_email_log/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsTransactionalEmailGetSchema = () => {
    const TransactionalEmailLogRetrieveParams = orvalSchemas.TransactionalEmailLogRetrieveParams()
    return TransactionalEmailLogRetrieveParams.omit({ project_id: true })
}

const workflowsTransactionalEmailGet = (): ToolBase<
    ReturnType<typeof WorkflowsTransactionalEmailGetSchema>,
    WithPostHogUrl<Schemas.TransactionalEmailLogDetail>
> => ({
    name: 'workflows-transactional-email-get',
    schema: WorkflowsTransactionalEmailGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsTransactionalEmailGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TransactionalEmailLogDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/transactional_email_log/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/transactional/log/${result.message_id}`)
    },
})

const WorkflowsTransactionalEmailResultsSchema = () => {
    const TransactionalEmailLogResultsRetrieveQueryParams =
        orvalSchemas.TransactionalEmailLogResultsRetrieveQueryParams()
    return TransactionalEmailLogResultsRetrieveQueryParams
}

const workflowsTransactionalEmailResults = (): ToolBase<
    ReturnType<typeof WorkflowsTransactionalEmailResultsSchema>,
    Schemas.TransactionalEmailResults
> => ({
    name: 'workflows-transactional-email-results',
    schema: WorkflowsTransactionalEmailResultsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsTransactionalEmailResultsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TransactionalEmailResults>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/transactional_email_log/results/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                event: params.event,
                revenue_property: params.revenue_property,
                window_days: params.window_days,
                workflow_id: params.workflow_id,
            },
        })
        return result
    },
})

const WorkflowsTransactionalEmailStatsSchema = () => {
    const TransactionalEmailLogStatsRetrieveQueryParams = orvalSchemas.TransactionalEmailLogStatsRetrieveQueryParams()
    return TransactionalEmailLogStatsRetrieveQueryParams
}

const workflowsTransactionalEmailStats = (): ToolBase<
    ReturnType<typeof WorkflowsTransactionalEmailStatsSchema>,
    Schemas.TransactionalEmailStats
> => ({
    name: 'workflows-transactional-email-stats',
    schema: WorkflowsTransactionalEmailStatsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsTransactionalEmailStatsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TransactionalEmailStats>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/transactional_email_log/stats/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                group_by: params.group_by,
            },
        })
        return result
    },
})

const WorkflowsTransactionalEmailsListSchema = () => {
    const TransactionalEmailLogListQueryParams = orvalSchemas.TransactionalEmailLogListQueryParams()
    return TransactionalEmailLogListQueryParams
}

const workflowsTransactionalEmailsList = (): ToolBase<
    ReturnType<typeof WorkflowsTransactionalEmailsListSchema>,
    Schemas.TransactionalEmailLogList
> => ({
    name: 'workflows-transactional-emails-list',
    schema: WorkflowsTransactionalEmailsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WorkflowsTransactionalEmailsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TransactionalEmailLogList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/transactional_email_log/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                status: params.status,
                workflow_id: params.workflow_id,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-transactional-email-get': workflowsTransactionalEmailGet,
    'workflows-transactional-email-results': workflowsTransactionalEmailResults,
    'workflows-transactional-email-stats': workflowsTransactionalEmailStats,
    'workflows-transactional-emails-list': workflowsTransactionalEmailsList,
}
