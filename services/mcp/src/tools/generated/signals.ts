// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsReportsListQueryParams,
    SignalsReportsRetrieveParams,
    SignalsScoutRunsFindingsCreateBody,
    SignalsScoutRunsFindingsCreateParams,
    SignalsScoutRunsListQueryParams,
    SignalsScoutRunsRetrieveParams,
    SignalsScoutScratchpadCreateBody,
    SignalsScoutScratchpadDeleteBody,
    SignalsScoutScratchpadListQueryParams,
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

const SignalsScoutRunsListSchema = SignalsScoutRunsListQueryParams

const signalsScoutRunsList = (): ToolBase<
    typeof SignalsScoutRunsListSchema,
    WithPostHogUrl<Schemas.SignalScoutRunSummary[]>
> => ({
    name: 'signals-scout-runs-list',
    schema: SignalsScoutRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutRunSummary[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                text: params.text,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutRunsRetrieveSchema = SignalsScoutRunsRetrieveParams.omit({ project_id: true })

const signalsScoutRunsRetrieve = (): ToolBase<typeof SignalsScoutRunsRetrieveSchema, Schemas.SignalScoutRunDetail> => ({
    name: 'signals-scout-runs-retrieve',
    schema: SignalsScoutRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutRunDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SignalsScoutRunsFindingsCreateSchema = SignalsScoutRunsFindingsCreateParams.omit({ project_id: true }).extend(
    SignalsScoutRunsFindingsCreateBody.shape
)

const signalsScoutRunsFindingsCreate = (): ToolBase<
    typeof SignalsScoutRunsFindingsCreateSchema,
    Schemas.EmitFindingResponse
> => ({
    name: 'signals-scout-runs-findings-create',
    schema: SignalsScoutRunsFindingsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsFindingsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.weight !== undefined) {
            body['weight'] = params.weight
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        if (params.hypothesis !== undefined) {
            body['hypothesis'] = params.hypothesis
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.dedupe_keys !== undefined) {
            body['dedupe_keys'] = params.dedupe_keys
        }
        if (params.time_range !== undefined) {
            body['time_range'] = params.time_range
        }
        if (params.mcp_trace_id !== undefined) {
            body['mcp_trace_id'] = params.mcp_trace_id
        }
        if (params.finding_id !== undefined) {
            body['finding_id'] = params.finding_id
        }
        const result = await context.api.request<Schemas.EmitFindingResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.id))}/findings/`,
            body,
        })
        return result
    },
})

const SignalsScoutScratchpadListSchema = SignalsScoutScratchpadListQueryParams

const signalsScoutScratchpadList = (): ToolBase<
    typeof SignalsScoutScratchpadListSchema,
    WithPostHogUrl<Schemas.ScratchpadEntry[]>
> => ({
    name: 'signals-scout-scratchpad-list',
    schema: SignalsScoutScratchpadListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScratchpadEntry[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/scratchpad/`,
            query: {
                include_expired: params.include_expired,
                limit: params.limit,
                tags: params.tags,
                text: params.text,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutScratchpadCreateSchema = SignalsScoutScratchpadCreateBody

const signalsScoutScratchpadCreate = (): ToolBase<
    typeof SignalsScoutScratchpadCreateSchema,
    Schemas.ScratchpadEntry
> => ({
    name: 'signals-scout-scratchpad-create',
    schema: SignalsScoutScratchpadCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.ttl_days !== undefined) {
            body['ttl_days'] = params.ttl_days
        }
        if (params.run_id !== undefined) {
            body['run_id'] = params.run_id
        }
        const result = await context.api.request<Schemas.ScratchpadEntry>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/scratchpad/`,
            body,
        })
        return result
    },
})

const SignalsScoutScratchpadDeleteSchema = SignalsScoutScratchpadDeleteBody

const signalsScoutScratchpadDelete = (): ToolBase<
    typeof SignalsScoutScratchpadDeleteSchema,
    Schemas.ForgetResponse
> => ({
    name: 'signals-scout-scratchpad-delete',
    schema: SignalsScoutScratchpadDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        const result = await context.api.request<Schemas.ForgetResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/scratchpad/delete/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'inbox-reports-list': inboxReportsList,
    'inbox-reports-retrieve': inboxReportsRetrieve,
    'inbox-source-configs-list': inboxSourceConfigsList,
    'inbox-source-configs-retrieve': inboxSourceConfigsRetrieve,
    'signals-scout-runs-list': signalsScoutRunsList,
    'signals-scout-runs-retrieve': signalsScoutRunsRetrieve,
    'signals-scout-runs-findings-create': signalsScoutRunsFindingsCreate,
    'signals-scout-scratchpad-list': signalsScoutScratchpadList,
    'signals-scout-scratchpad-create': signalsScoutScratchpadCreate,
    'signals-scout-scratchpad-delete': signalsScoutScratchpadDelete,
}
