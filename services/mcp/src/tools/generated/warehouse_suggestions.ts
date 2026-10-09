// AUTO-GENERATED from products/warehouse_suggestions/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/warehouse_suggestions/api'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WarehouseSuggestionsAcceptSchema = () => {
    const WarehouseSuggestionsAcceptCreateBody = orvalSchemas.WarehouseSuggestionsAcceptCreateBody()
    const WarehouseSuggestionsAcceptCreateParams = orvalSchemas.WarehouseSuggestionsAcceptCreateParams()
    return WarehouseSuggestionsAcceptCreateParams.omit({ project_id: true }).extend(
        WarehouseSuggestionsAcceptCreateBody.shape
    )
}

const WarehouseSuggestionsAcceptSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const warehouseSuggestionsAcceptPrepare = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsAcceptSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'warehouse-suggestions-accept-prepare',
    schema: WarehouseSuggestionsAcceptSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseSuggestionsAcceptSchema>>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'warehouse-suggestions-accept',
            actionLabel: 'accept warehouse suggestion',
            messageTemplate:
                "About to accept warehouse suggestion '{id}'. This applies the change it proposes to the view or table. If it is a materialize suggestion, the view then refreshes on a schedule, which adds a recurring compute cost. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { projectId: String(__scopeProjectId) },
        })
    },
})

const warehouseSuggestionsAcceptExecute = (): ToolBase<
    typeof WarehouseSuggestionsAcceptSchemaExecute,
    Schemas.WarehouseSuggestion
> => ({
    name: 'warehouse-suggestions-accept-execute',
    schema: WarehouseSuggestionsAcceptSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof WarehouseSuggestionsAcceptSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        const __guard = await executeConfirmedAction<z.infer<ReturnType<typeof WarehouseSuggestionsAcceptSchema>>>(
            context,
            {
                incomingArgs: confirmationParams,
                purpose: 'warehouse-suggestions-accept',
                codec: __runtime.codec,
                ledger: __runtime.ledger,
                stash: __runtime.stash,
                expectedScope: { projectId: String(__scopeProjectId) },
            }
        )
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const projectId = __scopeProjectId
        const body: Record<string, unknown> = {}
        if (params.refresh_interval_seconds !== undefined) {
            body['refresh_interval_seconds'] = params.refresh_interval_seconds
        }
        const result = await context.api.request<Schemas.WarehouseSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/${encodeURIComponent(String(params.id))}/accept/`,
            body,
        })
        return result
    },
})

const WarehouseSuggestionsDismissSchema = () => {
    const WarehouseSuggestionsDismissCreateBody = orvalSchemas.WarehouseSuggestionsDismissCreateBody()
    const WarehouseSuggestionsDismissCreateParams = orvalSchemas.WarehouseSuggestionsDismissCreateParams()
    return WarehouseSuggestionsDismissCreateParams.omit({ project_id: true }).extend(
        WarehouseSuggestionsDismissCreateBody.shape
    )
}

const warehouseSuggestionsDismiss = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsDismissSchema>,
    Schemas.WarehouseSuggestion
> => ({
    name: 'warehouse-suggestions-dismiss',
    schema: WarehouseSuggestionsDismissSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseSuggestionsDismissSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.reason !== undefined) {
            body['reason'] = params.reason
        }
        if (params.note !== undefined) {
            body['note'] = params.note
        }
        const result = await context.api.request<Schemas.WarehouseSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/${encodeURIComponent(String(params.id))}/dismiss/`,
            body,
        })
        return result
    },
})

const WarehouseSuggestionsGetSchema = () => {
    const WarehouseSuggestionsRetrieveParams = orvalSchemas.WarehouseSuggestionsRetrieveParams()
    return WarehouseSuggestionsRetrieveParams.omit({ project_id: true })
}

const warehouseSuggestionsGet = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsGetSchema>,
    Schemas.WarehouseSuggestion
> => ({
    name: 'warehouse-suggestions-get',
    schema: WarehouseSuggestionsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseSuggestionsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WarehouseSuggestion>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const WarehouseSuggestionsListSchema = () => {
    const WarehouseSuggestionsListQueryParams = orvalSchemas.WarehouseSuggestionsListQueryParams()
    return WarehouseSuggestionsListQueryParams
}

const warehouseSuggestionsList = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsListSchema>,
    WithPostHogUrl<Schemas.PaginatedWarehouseSuggestionList>
> => ({
    name: 'warehouse-suggestions-list',
    schema: WarehouseSuggestionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseSuggestionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedWarehouseSuggestionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/`,
            query: {
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'kind',
                    'subject_kind',
                    'subject_id',
                    'payload',
                    'status',
                    'score',
                    'can_act',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/models')
    },
})

const WarehouseSuggestionsResumeSchema = () => {
    const WarehouseSuggestionsResumeCreateParams = orvalSchemas.WarehouseSuggestionsResumeCreateParams()
    return WarehouseSuggestionsResumeCreateParams.omit({ project_id: true })
}

const warehouseSuggestionsResume = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsResumeSchema>,
    Schemas.WarehouseSuggestion
> => ({
    name: 'warehouse-suggestions-resume',
    schema: WarehouseSuggestionsResumeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseSuggestionsResumeSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WarehouseSuggestion>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/${encodeURIComponent(String(params.id))}/resume/`,
        })
        return result
    },
})

const WarehouseSuggestionsStatusSchema = () => z.object({})

const warehouseSuggestionsStatus = (): ToolBase<
    ReturnType<typeof WarehouseSuggestionsStatusSchema>,
    Schemas.WarehouseSuggestionStatus
> => ({
    name: 'warehouse-suggestions-status',
    schema: WarehouseSuggestionsStatusSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof WarehouseSuggestionsStatusSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WarehouseSuggestionStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_suggestions/status/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'warehouse-suggestions-accept-prepare': warehouseSuggestionsAcceptPrepare,
    'warehouse-suggestions-accept-execute': warehouseSuggestionsAcceptExecute,
    'warehouse-suggestions-dismiss': warehouseSuggestionsDismiss,
    'warehouse-suggestions-get': warehouseSuggestionsGet,
    'warehouse-suggestions-list': warehouseSuggestionsList,
    'warehouse-suggestions-resume': warehouseSuggestionsResume,
    'warehouse-suggestions-status': warehouseSuggestionsStatus,
}
