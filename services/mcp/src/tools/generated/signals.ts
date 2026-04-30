// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsAgentHarnessMemoryCreateBody,
    SignalsAgentHarnessMemoryForgetCreateBody,
    SignalsAgentHarnessMemoryListQueryParams,
    SignalsAgentHarnessRunsFindingsCreateBody,
    SignalsAgentHarnessRunsFindingsCreateParams,
    SignalsAgentHarnessRunsListQueryParams,
    SignalsAgentHarnessRunsRetrieveParams,
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

const SignalsAgentHarnessRunsListSchema = SignalsAgentHarnessRunsListQueryParams

const signalsAgentHarnessRunsList = (): ToolBase<
    typeof SignalsAgentHarnessRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalAgentRunSummaryList>
> => ({
    name: 'signals-agent-harness-runs-list',
    schema: SignalsAgentHarnessRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalAgentRunSummaryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/runs/`,
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

const SignalsAgentHarnessRunsRetrieveSchema = SignalsAgentHarnessRunsRetrieveParams.omit({ project_id: true })

const signalsAgentHarnessRunsRetrieve = (): ToolBase<
    typeof SignalsAgentHarnessRunsRetrieveSchema,
    Schemas.SignalAgentRunDetail
> => ({
    name: 'signals-agent-harness-runs-retrieve',
    schema: SignalsAgentHarnessRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalAgentRunDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SignalsAgentHarnessRunsFindingsCreateSchema = SignalsAgentHarnessRunsFindingsCreateParams.omit({
    project_id: true,
}).extend(SignalsAgentHarnessRunsFindingsCreateBody.shape)

const signalsAgentHarnessRunsFindingsCreate = (): ToolBase<
    typeof SignalsAgentHarnessRunsFindingsCreateSchema,
    Schemas.EmitFindingResponse
> => ({
    name: 'signals-agent-harness-runs-findings-create',
    schema: SignalsAgentHarnessRunsFindingsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessRunsFindingsCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/runs/${encodeURIComponent(String(params.id))}/findings/`,
            body,
        })
        return result
    },
})

const SignalsAgentHarnessMemoryListSchema = SignalsAgentHarnessMemoryListQueryParams

const signalsAgentHarnessMemoryList = (): ToolBase<
    typeof SignalsAgentHarnessMemoryListSchema,
    WithPostHogUrl<Schemas.PaginatedMemoryEntryList>
> => ({
    name: 'signals-agent-harness-memory-list',
    schema: SignalsAgentHarnessMemoryListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessMemoryListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMemoryEntryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/memory/`,
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

const SignalsAgentHarnessMemoryCreateSchema = SignalsAgentHarnessMemoryCreateBody

const signalsAgentHarnessMemoryCreate = (): ToolBase<
    typeof SignalsAgentHarnessMemoryCreateSchema,
    Schemas.MemoryEntry
> => ({
    name: 'signals-agent-harness-memory-create',
    schema: SignalsAgentHarnessMemoryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessMemoryCreateSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/memory/`,
            body,
        })
        return result
    },
})

const SignalsAgentHarnessMemoryForgetCreateSchema = SignalsAgentHarnessMemoryForgetCreateBody

const signalsAgentHarnessMemoryForgetCreate = (): ToolBase<
    typeof SignalsAgentHarnessMemoryForgetCreateSchema,
    Schemas.ForgetResponse
> => ({
    name: 'signals-agent-harness-memory-forget-create',
    schema: SignalsAgentHarnessMemoryForgetCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsAgentHarnessMemoryForgetCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        const result = await context.api.request<Schemas.ForgetResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/agent_harness/memory/forget/`,
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
    'signals-agent-harness-runs-list': signalsAgentHarnessRunsList,
    'signals-agent-harness-runs-retrieve': signalsAgentHarnessRunsRetrieve,
    'signals-agent-harness-runs-findings-create': signalsAgentHarnessRunsFindingsCreate,
    'signals-agent-harness-memory-list': signalsAgentHarnessMemoryList,
    'signals-agent-harness-memory-create': signalsAgentHarnessMemoryCreate,
    'signals-agent-harness-memory-forget-create': signalsAgentHarnessMemoryForgetCreate,
}
