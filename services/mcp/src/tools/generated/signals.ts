// AUTO-GENERATED from products/signals/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SignalsReportArtefactsCreateBody,
    SignalsReportArtefactsCreateParams,
    SignalsReportArtefactsDestroyParams,
    SignalsReportArtefactsListParams,
    SignalsReportArtefactsListQueryParams,
    SignalsReportArtefactsPartialUpdateBody,
    SignalsReportArtefactsPartialUpdateParams,
    SignalsReportArtefactsRetrieveParams,
    SignalsReportsBulkStateCreateBody,
    SignalsReportsListQueryParams,
    SignalsReportsPartialUpdateBody,
    SignalsReportsPartialUpdateParams,
    SignalsReportsRetrieveParams,
    SignalsReportsStateCreateBody,
    SignalsReportsStateCreateParams,
    SignalsScoutConfigCreateBody,
    SignalsScoutConfigDestroyParams,
    SignalsScoutConfigRunParams,
    SignalsScoutConfigUpdateBody,
    SignalsScoutConfigUpdateParams,
    SignalsScoutEditReportBody,
    SignalsScoutEditReportParams,
    SignalsScoutEmitReportBody,
    SignalsScoutEmitReportParams,
    SignalsScoutEmitSignalBody,
    SignalsScoutEmitSignalParams,
    SignalsScoutMembersListQueryParams,
    SignalsScoutNotifyBody,
    SignalsScoutNotifyParams,
    SignalsScoutProjectProfileGetQueryParams,
    SignalsScoutRunsEmissionReportsParams,
    SignalsScoutRunsEmissionsParams,
    SignalsScoutRunsListQueryParams,
    SignalsScoutRunsRecentEmissionsQueryParams,
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
import {
    withPostHogUrl,
    withAgentNote,
    pickResponseFields,
    type WithPostHogUrl,
    type WithAgentNote,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const InboxReportArtefactsCreateSchema = SignalsReportArtefactsCreateParams.omit({ project_id: true }).extend(
    SignalsReportArtefactsCreateBody.shape
)

const inboxReportArtefactsCreate = (): ToolBase<
    typeof InboxReportArtefactsCreateSchema,
    WithPostHogUrl<Schemas.SignalReportArtefactWriteResponse>
> => ({
    name: 'inbox-report-artefacts-create',
    schema: InboxReportArtefactsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportArtefactsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.artefact_type !== undefined) {
            body['artefact_type'] = params.artefact_type
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.SignalReportArtefactWriteResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.report_id))}/artefacts/`,
            body,
        })
        return await withPostHogUrl(context, result, `/inbox/${result.report_id}`)
    },
})

const InboxReportArtefactsDeleteSchema = SignalsReportArtefactsDestroyParams.omit({ project_id: true })

const inboxReportArtefactsDelete = (): ToolBase<typeof InboxReportArtefactsDeleteSchema, unknown> => ({
    name: 'inbox-report-artefacts-delete',
    schema: InboxReportArtefactsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportArtefactsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.report_id))}/artefacts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const InboxReportArtefactsListSchema = SignalsReportArtefactsListParams.omit({ project_id: true }).extend(
    SignalsReportArtefactsListQueryParams.shape
)

const inboxReportArtefactsList = (): ToolBase<
    typeof InboxReportArtefactsListSchema,
    WithPostHogUrl<Schemas.PaginatedSignalReportArtefactList>
> => ({
    name: 'inbox-report-artefacts-list',
    schema: InboxReportArtefactsListSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportArtefactsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalReportArtefactList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.report_id))}/artefacts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const InboxReportArtefactsRetrieveSchema = SignalsReportArtefactsRetrieveParams.omit({ project_id: true })

const inboxReportArtefactsRetrieve = (): ToolBase<
    typeof InboxReportArtefactsRetrieveSchema,
    WithPostHogUrl<Schemas.SignalReportArtefact>
> => ({
    name: 'inbox-report-artefacts-retrieve',
    schema: InboxReportArtefactsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportArtefactsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalReportArtefact>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.report_id))}/artefacts/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/inbox/${params.report_id}`)
    },
})

const InboxReportArtefactsUpdateSchema = SignalsReportArtefactsPartialUpdateParams.omit({ project_id: true }).extend(
    SignalsReportArtefactsPartialUpdateBody.shape
)

const inboxReportArtefactsUpdate = (): ToolBase<
    typeof InboxReportArtefactsUpdateSchema,
    Schemas.SignalReportArtefactWriteResponse
> => ({
    name: 'inbox-report-artefacts-update',
    schema: InboxReportArtefactsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportArtefactsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.SignalReportArtefactWriteResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.report_id))}/artefacts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const InboxReportsBulkSetStateSchema = SignalsReportsBulkStateCreateBody

const inboxReportsBulkSetState = (): ToolBase<
    typeof InboxReportsBulkSetStateSchema,
    Schemas.SignalReportBulkStateResponse
> => ({
    name: 'inbox-reports-bulk-set-state',
    schema: InboxReportsBulkSetStateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsBulkSetStateSchema>) => {
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
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.SignalReportBulkStateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/bulk-state/`,
            body,
        })
        return result
    },
})

const InboxReportsListSchema = SignalsReportsListQueryParams

const inboxReportsList = (): ToolBase<
    typeof InboxReportsListSchema,
    WithAgentNote<WithPostHogUrl<Schemas.PaginatedSignalReportList>>
> => ({
    name: 'inbox-reports-list',
    schema: InboxReportsListSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSignalReportList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/`,
            query: {
                has_implementation_pr: params.has_implementation_pr,
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                priority: params.priority,
                search: params.search,
                source_product: params.source_product,
                status: params.status,
                suggested_reviewers: params.suggested_reviewers,
                task_id: params.task_id,
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
                    'dismissal_reason',
                    'dismissal_note',
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
        return withAgentNote(
            await withPostHogUrl(
                context,
                {
                    ...filtered,
                    results: await Promise.all(
                        (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/inbox/${item.id}`))
                    ),
                },
                '/inbox'
            ),
            "If you do ANY work connected to one of these reports — even pure research or investigation — always first associate your task with it: call inbox-report-artefacts-create with artefact_type `task_run` and content {} (your own task id is filled in automatically). That task_run artefact IS the task↔report association — commits you push are recorded on the report through it, and without it your work is invisible to the report. If that call fails with a 400 saying a task id is required, you simply have no task id of your own — that's expected, not an error to fix; skip the association and carry on. Without the write tools (a read-only session) ignore the association step entirely — artefact persistence is handled for you. Read the report's work log via inbox-report-artefacts-list before acting."
        )
    },
})

const InboxReportsRetrieveSchema = SignalsReportsRetrieveParams.omit({ project_id: true })

const inboxReportsRetrieve = (): ToolBase<
    typeof InboxReportsRetrieveSchema,
    WithAgentNote<WithPostHogUrl<Schemas.SignalReport>>
> => ({
    name: 'inbox-reports-retrieve',
    schema: InboxReportsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.id))}/`,
        })
        return withAgentNote(
            await withPostHogUrl(context, result, `/inbox/${result.id}`),
            "If you do ANY work connected to this report — even pure research or investigation — always first associate your task with it: call inbox-report-artefacts-create with artefact_type `task_run` and content {} (your own task id is filled in automatically). That task_run artefact IS the task↔report association — commits you push via git_signed_commit are recorded on the report through it, and without it your work is invisible to the report. If that call fails with a 400 saying a task id is required, you simply have no task id of your own — that's expected, not an error to fix; skip the association and continue. Then log the work as artefacts as you go — notes, code references, and any commit you have already pushed to a remote branch outside git_signed_commit (signed pushes are recorded automatically; never record a commit that is not on a remote branch). Status artefacts (priority, actionability, reviewers) are latest-wins — append a new version to re-assess. Without the write tools, work as instructed by your task — artefact persistence is handled for you."
        )
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

const InboxReportsUpdateSchema = SignalsReportsPartialUpdateParams.omit({ project_id: true }).extend(
    SignalsReportsPartialUpdateBody.shape
)

const inboxReportsUpdate = (): ToolBase<typeof InboxReportsUpdateSchema, WithPostHogUrl<Schemas.SignalReport>> => ({
    name: 'inbox-reports-update',
    schema: InboxReportsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof InboxReportsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.summary !== undefined) {
            body['summary'] = params.summary
        }
        const result = await context.api.request<Schemas.SignalReport>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/reports/${encodeURIComponent(String(params.id))}/`,
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

const SignalsScoutConfigCreateSchema = SignalsScoutConfigCreateBody

const signalsScoutConfigCreate = (): ToolBase<typeof SignalsScoutConfigCreateSchema, Schemas.SignalScoutConfig> => ({
    name: 'signals-scout-config-create',
    schema: SignalsScoutConfigCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutConfigCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.skill_name !== undefined) {
            body['skill_name'] = params.skill_name
        }
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
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/`,
            body,
        })
        return result
    },
})

const SignalsScoutConfigDeleteSchema = SignalsScoutConfigDestroyParams.omit({ project_id: true })

const signalsScoutConfigDelete = (): ToolBase<typeof SignalsScoutConfigDeleteSchema, unknown> => ({
    name: 'signals-scout-config-delete',
    schema: SignalsScoutConfigDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutConfigDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/${encodeURIComponent(String(params.id))}/`,
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

const SignalsScoutConfigSyncSchema = z.object({})

const signalsScoutConfigSync = (): ToolBase<
    typeof SignalsScoutConfigSyncSchema,
    WithPostHogUrl<Schemas.SignalScoutConfig[]>
> => ({
    name: 'signals-scout-config-sync',
    schema: SignalsScoutConfigSyncSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof SignalsScoutConfigSyncSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutConfig[]>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/sync/`,
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

const SignalsScoutEditReportSchema = SignalsScoutEditReportParams.omit({ project_id: true }).extend(
    SignalsScoutEditReportBody.shape
)

const signalsScoutEditReport = (): ToolBase<typeof SignalsScoutEditReportSchema, Schemas.EditReportResponse> => ({
    name: 'signals-scout-edit-report',
    schema: SignalsScoutEditReportSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutEditReportSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.report_id !== undefined) {
            body['report_id'] = params.report_id
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.summary !== undefined) {
            body['summary'] = params.summary
        }
        if (params.append_note !== undefined) {
            body['append_note'] = params.append_note
        }
        if (params.suggested_reviewers !== undefined) {
            body['suggested_reviewers'] = params.suggested_reviewers
        }
        const result = await context.api.request<Schemas.EditReportResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/edit-report/`,
            body,
        })
        return result
    },
})

const SignalsScoutEmitReportSchema = SignalsScoutEmitReportParams.omit({ project_id: true }).extend(
    SignalsScoutEmitReportBody.shape
)

const signalsScoutEmitReport = (): ToolBase<typeof SignalsScoutEmitReportSchema, Schemas.EmitReportResponse> => ({
    name: 'signals-scout-emit-report',
    schema: SignalsScoutEmitReportSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutEmitReportSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.summary !== undefined) {
            body['summary'] = params.summary
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        if (params.actionability_explanation !== undefined) {
            body['actionability_explanation'] = params.actionability_explanation
        }
        if (params.actionability !== undefined) {
            body['actionability'] = params.actionability
        }
        if (params.already_addressed !== undefined) {
            body['already_addressed'] = params.already_addressed
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        if (params.priority_explanation !== undefined) {
            body['priority_explanation'] = params.priority_explanation
        }
        if (params.suggested_reviewers !== undefined) {
            body['suggested_reviewers'] = params.suggested_reviewers
        }
        const result = await context.api.request<Schemas.EmitReportResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/emit-report/`,
            body,
        })
        return result
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
        if (params.tags !== undefined) {
            body['tags'] = params.tags
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/emit-signal/`,
            body,
        })
        return result
    },
})

const SignalsScoutMembersListSchema = SignalsScoutMembersListQueryParams

const signalsScoutMembersList = (): ToolBase<
    typeof SignalsScoutMembersListSchema,
    WithPostHogUrl<Schemas.ScoutMember[]>
> => ({
    name: 'signals-scout-members-list',
    schema: SignalsScoutMembersListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutMembersListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScoutMember[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/members/`,
            query: {
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutNotifySchema = SignalsScoutNotifyParams.omit({ project_id: true }).extend(
    SignalsScoutNotifyBody.shape
)

const signalsScoutNotify = (): ToolBase<typeof SignalsScoutNotifySchema, Schemas.ScoutNotifyResponse> => ({
    name: 'signals-scout-notify',
    schema: SignalsScoutNotifySchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutNotifySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.account_name !== undefined) {
            body['account_name'] = params.account_name
        }
        if (params.owner_email !== undefined) {
            body['owner_email'] = params.owner_email
        }
        if (params.owner_label !== undefined) {
            body['owner_label'] = params.owner_label
        }
        if (params.report_id !== undefined) {
            body['report_id'] = params.report_id
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        const result = await context.api.request<Schemas.ScoutNotifyResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/notify/`,
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

const SignalsScoutRunNowSchema = SignalsScoutConfigRunParams.omit({ project_id: true })

const signalsScoutRunNow = (): ToolBase<typeof SignalsScoutRunNowSchema, unknown> => ({
    name: 'signals-scout-run-now',
    schema: SignalsScoutRunNowSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunNowSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/configs/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

const SignalsScoutRunsEmissionReportsSchema = SignalsScoutRunsEmissionReportsParams.omit({ project_id: true })

const signalsScoutRunsEmissionReports = (): ToolBase<
    typeof SignalsScoutRunsEmissionReportsSchema,
    WithPostHogUrl<Schemas.ScoutEmissionReportLink[]>
> => ({
    name: 'signals-scout-runs-emission-reports',
    schema: SignalsScoutRunsEmissionReportsSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsEmissionReportsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ScoutEmissionReportLink[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/emissions/reports/`,
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutRunsEmissionsListSchema = SignalsScoutRunsEmissionsParams.omit({ project_id: true })

const signalsScoutRunsEmissionsList = (): ToolBase<
    typeof SignalsScoutRunsEmissionsListSchema,
    WithPostHogUrl<Schemas.SignalScoutEmission[]>
> => ({
    name: 'signals-scout-runs-emissions-list',
    schema: SignalsScoutRunsEmissionsListSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsEmissionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutEmission[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/emissions/`,
        })
        return await withPostHogUrl(context, result, '/inbox')
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
                emitted: params.emitted,
                limit: params.limit,
                skill_name: params.skill_name,
                skill_version: params.skill_version,
                text: params.text,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

const SignalsScoutRunsRecentEmissionsSchema = SignalsScoutRunsRecentEmissionsQueryParams

const signalsScoutRunsRecentEmissions = (): ToolBase<
    typeof SignalsScoutRunsRecentEmissionsSchema,
    WithPostHogUrl<Schemas.SignalScoutEmission[]>
> => ({
    name: 'signals-scout-runs-recent-emissions',
    schema: SignalsScoutRunsRecentEmissionsSchema,
    handler: async (context: Context, params: z.infer<typeof SignalsScoutRunsRecentEmissionsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SignalScoutEmission[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/emissions/recent/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                limit: params.limit,
                skill_name: params.skill_name,
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/signals/scout/runs/${encodeURIComponent(String(params.run_id))}/`,
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
                content_max_chars: params.content_max_chars,
                date_from: params.date_from,
                date_to: params.date_to,
                keys_only: params.keys_only,
                limit: params.limit,
                text: params.text,
            },
        })
        return await withPostHogUrl(context, result, '/inbox')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'inbox-report-artefacts-create': inboxReportArtefactsCreate,
    'inbox-report-artefacts-delete': inboxReportArtefactsDelete,
    'inbox-report-artefacts-list': inboxReportArtefactsList,
    'inbox-report-artefacts-retrieve': inboxReportArtefactsRetrieve,
    'inbox-report-artefacts-update': inboxReportArtefactsUpdate,
    'inbox-reports-bulk-set-state': inboxReportsBulkSetState,
    'inbox-reports-list': inboxReportsList,
    'inbox-reports-retrieve': inboxReportsRetrieve,
    'inbox-reports-set-state': inboxReportsSetState,
    'inbox-reports-update': inboxReportsUpdate,
    'inbox-source-configs-create': inboxSourceConfigsCreate,
    'inbox-source-configs-list': inboxSourceConfigsList,
    'inbox-source-configs-partial-update': inboxSourceConfigsPartialUpdate,
    'inbox-source-configs-retrieve': inboxSourceConfigsRetrieve,
    'inbox-source-configs-update': inboxSourceConfigsUpdate,
    'signals-scout-config-create': signalsScoutConfigCreate,
    'signals-scout-config-delete': signalsScoutConfigDelete,
    'signals-scout-config-list': signalsScoutConfigList,
    'signals-scout-config-sync': signalsScoutConfigSync,
    'signals-scout-config-update': signalsScoutConfigUpdate,
    'signals-scout-edit-report': signalsScoutEditReport,
    'signals-scout-emit-report': signalsScoutEmitReport,
    'signals-scout-emit-signal': signalsScoutEmitSignal,
    'signals-scout-members-list': signalsScoutMembersList,
    'signals-scout-notify': signalsScoutNotify,
    'signals-scout-project-profile-get': signalsScoutProjectProfileGet,
    'signals-scout-run-now': signalsScoutRunNow,
    'signals-scout-runs-emission-reports': signalsScoutRunsEmissionReports,
    'signals-scout-runs-emissions-list': signalsScoutRunsEmissionsList,
    'signals-scout-runs-list': signalsScoutRunsList,
    'signals-scout-runs-recent-emissions': signalsScoutRunsRecentEmissions,
    'signals-scout-runs-retrieve': signalsScoutRunsRetrieve,
    'signals-scout-scratchpad-forget': signalsScoutScratchpadForget,
    'signals-scout-scratchpad-remember': signalsScoutScratchpadRemember,
    'signals-scout-scratchpad-search': signalsScoutScratchpadSearch,
}
