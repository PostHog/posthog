// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsReportsListQueryParams,
    SignalsReportsRetrieveParams,
    SignalsSourceConfigsListQueryParams,
    SignalsSourceConfigsRetrieveParams,
} from '@/generated/signals/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const InboxReportsListSchema = SignalsReportsListQueryParams

const inboxReportsList = (): ToolBase<
    typeof InboxReportsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalReportList>
> => ({
    name: 'inbox-reports-list',
    schema: InboxReportsListSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalReportList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                search: params.search,
                source_product: params.source_product,
                status: params.status,
                suggested_reviewers: params.suggested_reviewers,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'title',
                    'summary',
                    'status',
                    'priority',
                    'actionability',
                    'already_addressed',
                    'signal_count',
                    'total_weight',
                    'source_products',
                    'is_suggested_reviewer',
                    'implementation_pr_url',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/inbox/${item.id}`))
                ),
            },
            '/inbox'
        )
    },
})

const InboxReportsRetrieveSchema = SignalsReportsRetrieveParams.omit({ project_id: true })

const inboxReportsRetrieve = (): ToolBase<typeof InboxReportsRetrieveSchema, WithPostHogUrl<Schemas.SignalReport>> => ({
    name: 'inbox-reports-retrieve',
    schema: InboxReportsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/inbox/${result.id}`)
    },
})

const InboxSourceConfigsListSchema = SignalsSourceConfigsListQueryParams

const inboxSourceConfigsList = (): ToolBase<
    typeof InboxSourceConfigsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalSourceConfigList>
> => ({
    name: 'inbox-source-configs-list',
    schema: InboxSourceConfigsListSchema,
    handler: async (context: Context, params: z.infer<typeof InboxSourceConfigsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalSourceConfigList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'source_product',
                    'source_type',
                    'enabled',
                    'status',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/inbox')
    },
})

const InboxSourceConfigsRetrieveSchema = SignalsSourceConfigsRetrieveParams.omit({ project_id: true })

const inboxSourceConfigsRetrieve = (): ToolBase<
    typeof InboxSourceConfigsRetrieveSchema,
    Schemas.SignalSourceConfig
> => ({
    name: 'inbox-source-configs-retrieve',
    schema: InboxSourceConfigsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InboxSourceConfigsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalSourceConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'inbox-reports-list': inboxReportsList,
    'inbox-reports-retrieve': inboxReportsRetrieve,
    'inbox-source-configs-list': inboxSourceConfigsList,
    'inbox-source-configs-retrieve': inboxSourceConfigsRetrieve,
}
