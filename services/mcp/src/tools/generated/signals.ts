// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsReportsListQueryParams,
    SignalsReportsRetrieveParams,
    SignalsReportsStateCreateBody,
    SignalsReportsStateCreateParams,
    SignalsScoutConfigUpdateBody,
    SignalsScoutConfigUpdateParams,
    SignalsScoutEmitSignalBody,
    SignalsScoutEmitSignalParams,
    SignalsScoutProjectProfileGetQueryParams,
    SignalsScoutRunsListQueryParams,
    SignalsScoutRunsRetrieveParams,
    SignalsScoutScratchpadForgetBody,
    SignalsScoutScratchpadRememberBody,
    SignalsScoutScratchpadSearchQueryParams,
    SignalsSourceConfigsCreateBody,
    SignalsSourceConfigsListQueryParams,
    SignalsSourceConfigsPartialUpdateBody,
    SignalsSourceConfigsPartialUpdateParams,
    SignalsSourceConfigsRetrieveParams,
    SignalsSourceConfigsUpdateBody,
    SignalsSourceConfigsUpdateParams,
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
                priority: params.priority,
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

const InboxReportsSetStateSchema = SignalsReportsStateCreateParams.omit({ project_id: true }).extend(
    SignalsReportsStateCreateBody.shape
)

const inboxReportsSetState = (): ToolBase<typeof InboxReportsSetStateSchema, WithPostHogUrl<Schemas.SignalReport>> => ({
    name: 'inbox-reports-set-state',
    schema: InboxReportsSetStateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsSetStateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.state !== undefined) {
            body['state'] = params.state
        }
        if (params.dismissal_reason !== undefined) {
            body['dismissal_reason'] = params.dismissal_reason
        }
        if (params.dismissal_note !== undefined) {
            body['dismissal_note'] = params.dismissal_note
        }
        if (params.snooze_for !== undefined) {
            body['snooze_for'] = params.snooze_for
        }
        const result = await context.api.request<Schemas.SignalReport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.id))}/state/`,
            body,
        })
        return await withPostHogUrl(context, result, `/inbox/${result.id}`)
    },
})

const InboxSourceConfigsCreateSchema = SignalsSourceConfigsCreateBody

const inboxSourceConfigsCreate = (): ToolBase<typeof InboxSourceConfigsCreateSchema, Schemas.SignalSourceConfig> => ({
    name: 'inbox-source-configs-create',
    schema: InboxSourceConfigsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxSourceConfigsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_product !== undefined) {
            body['source_product'] = params.source_product
        }
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.SignalSourceConfig>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/`,
            body,
        })
        return result
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

const InboxSourceConfigsPartialUpdateSchema = SignalsSourceConfigsPartialUpdateParams.omit({ project_id: true }).extend(
    SignalsSourceConfigsPartialUpdateBody.shape
)

const inboxSourceConfigsPartialUpdate = (): ToolBase<
    typeof InboxSourceConfigsPartialUpdateSchema,
    Schemas.SignalSourceConfig
> => ({
    name: 'inbox-source-configs-partial-update',
    schema: InboxSourceConfigsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxSourceConfigsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_product !== undefined) {
            body['source_product'] = params.source_product
        }
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.SignalSourceConfig>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
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

const InboxSourceConfigsUpdateSchema = SignalsSourceConfigsUpdateParams.omit({ project_id: true }).extend(
    SignalsSourceConfigsUpdateBody.shape
)

const inboxSourceConfigsUpdate = (): ToolBase<typeof InboxSourceConfigsUpdateSchema, Schemas.SignalSourceConfig> => ({
    name: 'inbox-source-configs-update',
    schema: InboxSourceConfigsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxSourceConfigsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_product !== undefined) {
            body['source_product'] = params.source_product
        }
        if (params.source_type !== undefined) {
            body['source_type'] = params.source_type
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        const result = await context.api.request<Schemas.SignalSourceConfig>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/source_configs/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const SignalsScoutConfigListSchema = z.object({})

const signalsScoutConfigList = (): ToolBase<
    typeof SignalsScoutConfigListSchema,
    WithPostHogUrl<Schemas.SignalScoutConfig[]>
> => ({
    name: 'signals-scout-config-list',
    schema: SignalsScoutConfigListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof SignalsScoutConfigListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutConfig[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/`,
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutConfigUpdateSchema = SignalsScoutConfigUpdateParams.omit({ project_id: true }).extend(
    SignalsScoutConfigUpdateBody.shape
)

const signalsScoutConfigUpdate = (): ToolBase<
    typeof SignalsScoutConfigUpdateSchema,
    WithPostHogUrl<Schemas.SignalScoutConfig>
> => ({
    name: 'signals-scout-config-update',
    schema: SignalsScoutConfigUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutConfigUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.emit !== undefined) {
            body['emit'] = params.emit
        }
        if (params.run_interval_minutes !== undefined) {
            body['run_interval_minutes'] = params.run_interval_minutes
        }
        const result = await context.api.request<Schemas.SignalScoutConfig>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/inbox/${result.id}`)
    },
})

const SignalsScoutEmitSignalSchema = SignalsScoutEmitSignalParams.omit({ project_id: true }).extend(
    SignalsScoutEmitSignalBody.shape
)

const signalsScoutEmitSignal = (): ToolBase<typeof SignalsScoutEmitSignalSchema, Schemas.EmitFindingResponse> => ({
    name: 'signals-scout-emit-signal',
    schema: SignalsScoutEmitSignalSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutEmitSignalSchema>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.id))}/emit-signal/`,
            body,
        })
        return result
    },
})

const SignalsScoutProjectProfileGetSchema = SignalsScoutProjectProfileGetQueryParams

const signalsScoutProjectProfileGet = (): ToolBase<
    typeof SignalsScoutProjectProfileGetSchema,
    Schemas.ProjectProfile
> => ({
    name: 'signals-scout-project-profile-get',
    schema: SignalsScoutProjectProfileGetSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutProjectProfileGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ProjectProfile>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/project_profile/current/`,
            query: {
                force_refresh: params.force_refresh,
            },
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

const SignalsScoutScratchpadForgetSchema = SignalsScoutScratchpadForgetBody

const signalsScoutScratchpadForget = (): ToolBase<
    typeof SignalsScoutScratchpadForgetSchema,
    Schemas.ForgetResponse
> => ({
    name: 'signals-scout-scratchpad-forget',
    schema: SignalsScoutScratchpadForgetSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadForgetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        const result = await context.api.request<Schemas.ForgetResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/scratchpad/forget/`,
            body,
        })
        return result
    },
})

const SignalsScoutScratchpadRememberSchema = SignalsScoutScratchpadRememberBody

const signalsScoutScratchpadRemember = (): ToolBase<
    typeof SignalsScoutScratchpadRememberSchema,
    Schemas.ScratchpadEntry
> => ({
    name: 'signals-scout-scratchpad-remember',
    schema: SignalsScoutScratchpadRememberSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadRememberSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.content !== undefined) {
            body['content'] = params.content
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

const SignalsScoutScratchpadSearchSchema = SignalsScoutScratchpadSearchQueryParams

const signalsScoutScratchpadSearch = (): ToolBase<
    typeof SignalsScoutScratchpadSearchSchema,
    WithPostHogUrl<Schemas.ScratchpadEntry[]>
> => ({
    name: 'signals-scout-scratchpad-search',
    schema: SignalsScoutScratchpadSearchSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutScratchpadSearchSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScratchpadEntry[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/scratchpad/`,
            query: {
                limit: params.limit,
                text: params.text,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'inbox-reports-list': inboxReportsList,
    'inbox-reports-retrieve': inboxReportsRetrieve,
    'inbox-reports-set-state': inboxReportsSetState,
    'inbox-source-configs-create': inboxSourceConfigsCreate,
    'inbox-source-configs-list': inboxSourceConfigsList,
    'inbox-source-configs-partial-update': inboxSourceConfigsPartialUpdate,
    'inbox-source-configs-retrieve': inboxSourceConfigsRetrieve,
    'inbox-source-configs-update': inboxSourceConfigsUpdate,
    'signals-scout-config-list': signalsScoutConfigList,
    'signals-scout-config-update': signalsScoutConfigUpdate,
    'signals-scout-emit-signal': signalsScoutEmitSignal,
    'signals-scout-project-profile-get': signalsScoutProjectProfileGet,
    'signals-scout-runs-list': signalsScoutRunsList,
    'signals-scout-runs-retrieve': signalsScoutRunsRetrieve,
    'signals-scout-scratchpad-forget': signalsScoutScratchpadForget,
    'signals-scout-scratchpad-remember': signalsScoutScratchpadRemember,
    'signals-scout-scratchpad-search': signalsScoutScratchpadSearch,
}
