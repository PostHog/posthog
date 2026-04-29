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

const SignalsReportsListSchema = SignalsReportsListQueryParams

const signalsReportsList = (): ToolBase<
    typeof SignalsReportsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalReportList>
> => ({
    name: 'signals-reports-list',
    schema: SignalsReportsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsReportsListSchema>) => {
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
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/signals/${item.id}`))
                ),
            },
            '/signals'
        )
    },
})

const SignalsReportsRetrieveSchema = SignalsReportsRetrieveParams.omit({ project_id: true })

const signalsReportsRetrieve = (): ToolBase<
    typeof SignalsReportsRetrieveSchema,
    WithPostHogUrl<Schemas.SignalReport>
> => ({
    name: 'signals-reports-retrieve',
    schema: SignalsReportsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsReportsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/signals/${result.id}`)
    },
})

const SignalsSourceConfigsListSchema = SignalsSourceConfigsListQueryParams

const signalsSourceConfigsList = (): ToolBase<
    typeof SignalsSourceConfigsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalSourceConfigList>
> => ({
    name: 'signals-source-configs-list',
    schema: SignalsSourceConfigsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsSourceConfigsListSchema>) => {
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
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/signals/${item.id}`))
                ),
            },
            '/signals'
        )
    },
})

const SignalsSourceConfigsRetrieveSchema = SignalsSourceConfigsRetrieveParams.omit({ project_id: true })

const signalsSourceConfigsRetrieve = (): ToolBase<
    typeof SignalsSourceConfigsRetrieveSchema,
    WithPostHogUrl<Schemas.SignalSourceConfig>
> => ({
    name: 'signals-source-configs-retrieve',
    schema: SignalsSourceConfigsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsSourceConfigsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalSourceConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/signals/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'signals-reports-list': signalsReportsList,
    'signals-reports-retrieve': signalsReportsRetrieve,
    'signals-source-configs-list': signalsSourceConfigsList,
    'signals-source-configs-retrieve': signalsSourceConfigsRetrieve,
}
