// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsAgentMemoryCreateBody,
    SignalsAgentMemoryDeleteBody,
    SignalsAgentMemoryListQueryParams,
    SignalsAgentRunsFindingsCreateBody,
    SignalsAgentRunsFindingsCreateParams,
    SignalsAgentRunsListQueryParams,
    SignalsAgentRunsRetrieveParams,
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

const SignalsAgentRunsListSchema = SignalsAgentRunsListQueryParams

const signalsAgentRunsList = (): ToolBase<
    typeof SignalsAgentRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalAgentRunSummaryList>
> => ({
    name: 'signals-agent-runs-list',
    schema: SignalsAgentRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalAgentRunSummaryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                since: params.since,
                text: params.text,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'run_id',
                    'skill_name',
                    'skill_version',
                    'status',
                    'started_at',
                    'completed_at',
                    'summary',
                    'findings_count',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/inbox')
    },
})

const SignalsAgentRunsRetrieveSchema = SignalsAgentRunsRetrieveParams.omit({ project_id: true })

const signalsAgentRunsRetrieve = (): ToolBase<typeof SignalsAgentRunsRetrieveSchema, Schemas.SignalAgentRunDetail> => ({
    name: 'signals-agent-runs-retrieve',
    schema: SignalsAgentRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalAgentRunDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SignalsAgentRunsFindingsCreateSchema = SignalsAgentRunsFindingsCreateParams.omit({ project_id: true }).extend(
    SignalsAgentRunsFindingsCreateBody.shape
)

const signalsAgentRunsFindingsCreate = (): ToolBase<
    typeof SignalsAgentRunsFindingsCreateSchema,
    Schemas.EmitFindingResponse
> => ({
    name: 'signals-agent-runs-findings-create',
    schema: SignalsAgentRunsFindingsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentRunsFindingsCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/runs/${encodeURIComponent(String(params.id))}/findings/`,
            body,
        })
        return result
    },
})

const SignalsAgentMemoryListSchema = SignalsAgentMemoryListQueryParams

const signalsAgentMemoryList = (): ToolBase<
    typeof SignalsAgentMemoryListSchema,
    WithPostHogUrl<Schemas.PaginatedMemoryEntryList>
> => ({
    name: 'signals-agent-memory-list',
    schema: SignalsAgentMemoryListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentMemoryListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMemoryEntryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/memory/`,
            query: {
                include_expired: params.include_expired,
                limit: params.limit,
                offset: params.offset,
                tags: params.tags,
                text: params.text,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'key',
                    'content',
                    'authority',
                    'tags',
                    'created_at',
                    'updated_at',
                    'expires_at',
                    'created_by_run_id',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/inbox')
    },
})

const SignalsAgentMemoryCreateSchema = SignalsAgentMemoryCreateBody

const signalsAgentMemoryCreate = (): ToolBase<typeof SignalsAgentMemoryCreateSchema, Schemas.MemoryEntry> => ({
    name: 'signals-agent-memory-create',
    schema: SignalsAgentMemoryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentMemoryCreateSchema>) => {
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
        const result = await context.api.request<Schemas.MemoryEntry>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/memory/`,
            body,
        })
        return result
    },
})

const SignalsAgentProjectProfileGetSchema = z.object({})

const signalsAgentProjectProfileGet = (): ToolBase<
    typeof SignalsAgentProjectProfileGetSchema,
    Schemas.ProjectProfile[]
> => ({
    name: 'signals-agent-project-profile-get',
    schema: SignalsAgentProjectProfileGetSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof SignalsAgentProjectProfileGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ProjectProfile[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/project_profile/`,
        })
        return result
    },
})

const SignalsAgentMemoryDeleteSchema = SignalsAgentMemoryDeleteBody

const signalsAgentMemoryDelete = (): ToolBase<typeof SignalsAgentMemoryDeleteSchema, Schemas.ForgetResponse> => ({
    name: 'signals-agent-memory-delete',
    schema: SignalsAgentMemoryDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentMemoryDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        const result = await context.api.request<Schemas.ForgetResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent/memory/delete/`,
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
    'signals-agent-runs-list': signalsAgentRunsList,
    'signals-agent-runs-retrieve': signalsAgentRunsRetrieve,
    'signals-agent-runs-findings-create': signalsAgentRunsFindingsCreate,
    'signals-agent-memory-list': signalsAgentMemoryList,
    'signals-agent-memory-create': signalsAgentMemoryCreate,
    'signals-agent-project-profile-get': signalsAgentProjectProfileGet,
    'signals-agent-memory-delete': signalsAgentMemoryDelete,
}
