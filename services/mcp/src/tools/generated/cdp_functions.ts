// AUTO-GENERATED from products/cdp/mcp/cdp_functions.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFunctionsCreateBody,
    HogFunctionsDestroyParams,
    HogFunctionsDiscardDraftCreateParams,
    HogFunctionsInvocationsCreateBody,
    HogFunctionsInvocationsCreateParams,
    HogFunctionsListQueryParams,
    HogFunctionsLogsRetrieveParams,
    HogFunctionsLogsRetrieveQueryParams,
    HogFunctionsMetricsRetrieveParams,
    HogFunctionsMetricsRetrieveQueryParams,
    HogFunctionsPartialUpdateBody,
    HogFunctionsPartialUpdateParams,
    HogFunctionsPublishCreateBody,
    HogFunctionsPublishCreateParams,
    HogFunctionsRearrangePartialUpdateBody,
    HogFunctionsRetrieveParams,
    HogFunctionsRevisionsListParams,
    HogFunctionsRevisionsListQueryParams,
    HogFunctionsRevisionsRestoreCreateBody,
    HogFunctionsRevisionsRestoreCreateParams,
    HogFunctionsRevisionsRetrieveParams,
} from '@/generated/cdp_functions/api'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CdpFunctionsCreateSchema = HogFunctionsCreateBody.extend({
    type: HogFunctionsCreateBody.shape['type'].describe(
        'Function type. One of: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, transformation.'
    ),
    template_id: HogFunctionsCreateBody.shape['template_id'].describe(
        'ID of a HogFunctionTemplate to derive defaults from (code, inputs_schema, icon, name, description). Use the cdp-function-templates-list tool to find available templates.'
    ),
    hog: HogFunctionsCreateBody.shape['hog'].describe(
        'Source code for the function. For most types this is Hog code; for site_destination and site_app types this is TypeScript. Required if no template_id is provided.'
    ),
    enabled: HogFunctionsCreateBody.shape['enabled'].describe('Whether the function is active and processing events.'),
    execution_order: HogFunctionsCreateBody.shape['execution_order'].describe(
        'Execution priority for transformation functions (lower runs first). Only applies to type=transformation. If omitted, the function is appended at the end.'
    ),
})

const cdpFunctionsCreate = (): ToolBase<typeof CdpFunctionsCreateSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-create',
    schema: CdpFunctionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/`,
            body,
        })
        const filtered = omitResponseFields(result, ['inputs.*.value', 'mappings.*.inputs.*.value']) as typeof result
        return filtered
    },
})

const CdpFunctionsDeleteSchema = HogFunctionsDestroyParams.omit({ project_id: true })

const cdpFunctionsDelete = (): ToolBase<typeof CdpFunctionsDeleteSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-delete',
    schema: CdpFunctionsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const CdpFunctionsDiscardDraftSchema = HogFunctionsDiscardDraftCreateParams.omit({ project_id: true })

const cdpFunctionsDiscardDraft = (): ToolBase<typeof CdpFunctionsDiscardDraftSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-discard-draft',
    schema: CdpFunctionsDiscardDraftSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsDiscardDraftSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/discard_draft/`,
        })
        return result
    },
})

const CdpFunctionsGetRevisionSchema = HogFunctionsRevisionsRetrieveParams.omit({ project_id: true })

const cdpFunctionsGetRevision = (): ToolBase<typeof CdpFunctionsGetRevisionSchema, Schemas.HogFunctionRevision> => ({
    name: 'cdp-functions-get-revision',
    schema: CdpFunctionsGetRevisionSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsGetRevisionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunctionRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/revisions/${encodeURIComponent(String(params.version))}/`,
        })
        return result
    },
})

const CdpFunctionsInvocationsCreateSchema = HogFunctionsInvocationsCreateParams.omit({ project_id: true }).extend(
    HogFunctionsInvocationsCreateBody.shape
)

const cdpFunctionsInvocationsCreate = (): ToolBase<
    typeof CdpFunctionsInvocationsCreateSchema,
    Schemas.HogFunctionInvocation
> => ({
    name: 'cdp-functions-invocations-create',
    schema: CdpFunctionsInvocationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsInvocationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.configuration !== undefined) {
            body['configuration'] = params.configuration
        }
        if (params.use_draft !== undefined) {
            body['use_draft'] = params.use_draft
        }
        if (params.globals !== undefined) {
            body['globals'] = params.globals
        }
        if (params.clickhouse_event !== undefined) {
            body['clickhouse_event'] = params.clickhouse_event
        }
        if (params.mock_async_functions !== undefined) {
            body['mock_async_functions'] = params.mock_async_functions
        }
        if (params.invocation_id !== undefined) {
            body['invocation_id'] = params.invocation_id
        }
        const result = await context.api.request<Schemas.HogFunctionInvocation>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/invocations/`,
            body,
        })
        return result
    },
})

const CdpFunctionsListSchema = HogFunctionsListQueryParams

const cdpFunctionsList = (): ToolBase<
    typeof CdpFunctionsListSchema,
    WithPostHogUrl<Schemas.PaginatedHogFunctionMinimalList>
> => ({
    name: 'cdp-functions-list',
    schema: CdpFunctionsListSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionMinimalList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/`,
            query: {
                created_at: params.created_at,
                created_by: params.created_by,
                enabled: params.enabled,
                id: params.id,
                limit: params.limit,
                offset: params.offset,
                type: Array.isArray(params.type) ? params.type.join(',') || undefined : params.type,
                updated_at: params.updated_at,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'type',
                    'name',
                    'description',
                    'enabled',
                    'execution_order',
                    'icon_url',
                    'template.id',
                    'status',
                    'created_at',
                    'updated_at',
                    'created_by',
                    'filters',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/pipeline')
    },
})

const CdpFunctionsListRevisionsSchema = HogFunctionsRevisionsListParams.omit({ project_id: true }).extend(
    HogFunctionsRevisionsListQueryParams.shape
)

const cdpFunctionsListRevisions = (): ToolBase<
    typeof CdpFunctionsListRevisionsSchema,
    WithPostHogUrl<Schemas.PaginatedHogFunctionRevisionBasicList>
> => ({
    name: 'cdp-functions-list-revisions',
    schema: CdpFunctionsListRevisionsSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsListRevisionsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFunctionRevisionBasicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/revisions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/pipeline')
    },
})

const CdpFunctionsLogsRetrieveSchema = HogFunctionsLogsRetrieveParams.omit({ project_id: true }).extend(
    HogFunctionsLogsRetrieveQueryParams.shape
)

const cdpFunctionsLogsRetrieve = (): ToolBase<typeof CdpFunctionsLogsRetrieveSchema, unknown> => ({
    name: 'cdp-functions-logs-retrieve',
    schema: CdpFunctionsLogsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsLogsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/logs/`,
            query: {
                after: params.after,
                before: params.before,
                instance_id: params.instance_id,
                level: params.level,
                limit: params.limit,
                search: params.search,
            },
        })
        return result
    },
})

const CdpFunctionsMetricsRetrieveSchema = HogFunctionsMetricsRetrieveParams.omit({ project_id: true }).extend(
    HogFunctionsMetricsRetrieveQueryParams.shape
)

const cdpFunctionsMetricsRetrieve = (): ToolBase<
    typeof CdpFunctionsMetricsRetrieveSchema,
    Schemas.AppMetricsResponse
> => ({
    name: 'cdp-functions-metrics-retrieve',
    schema: CdpFunctionsMetricsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsMetricsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppMetricsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/metrics/`,
            query: {
                after: params.after,
                before: params.before,
                breakdown_by: params.breakdown_by,
                instance_id: params.instance_id,
                interval: params.interval,
                kind: params.kind,
                name: params.name,
            },
        })
        return result
    },
})

const CdpFunctionsPartialUpdateSchema = HogFunctionsPartialUpdateParams.omit({ project_id: true })
    .extend(HogFunctionsPartialUpdateBody.shape)
    .extend({
        enabled: HogFunctionsPartialUpdateBody.shape['enabled'].describe(
            'Set to true to activate or false to deactivate the function.'
        ),
    })

const cdpFunctionsPartialUpdate = (): ToolBase<typeof CdpFunctionsPartialUpdateSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-partial-update',
    schema: CdpFunctionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.hog !== undefined) {
            body['hog'] = params.hog
        }
        if (params.inputs_schema !== undefined) {
            body['inputs_schema'] = params.inputs_schema
        }
        if (params.inputs !== undefined) {
            body['inputs'] = params.inputs
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.masking !== undefined) {
            body['masking'] = params.masking
        }
        if (params.mappings !== undefined) {
            body['mappings'] = params.mappings
        }
        if (params.icon_url !== undefined) {
            body['icon_url'] = params.icon_url
        }
        if (params.template_id !== undefined) {
            body['template_id'] = params.template_id
        }
        if (params.execution_order !== undefined) {
            body['execution_order'] = params.execution_order
        }
        if (params.base_updated_at !== undefined) {
            body['base_updated_at'] = params.base_updated_at
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = omitResponseFields(result, ['inputs.*.value', 'mappings.*.inputs.*.value']) as typeof result
        return filtered
    },
})

const CdpFunctionsPublishSchema = HogFunctionsPublishCreateParams.omit({ project_id: true }).extend(
    HogFunctionsPublishCreateBody.shape
)

const cdpFunctionsPublish = (): ToolBase<typeof CdpFunctionsPublishSchema, Schemas.HogFunctionPublishResponse> => ({
    name: 'cdp-functions-publish',
    schema: CdpFunctionsPublishSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsPublishSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.confirm !== undefined) {
            body['confirm'] = params.confirm
        }
        if (params.confirm_token !== undefined) {
            body['confirm_token'] = params.confirm_token
        }
        const result = await context.api.request<Schemas.HogFunctionPublishResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/publish/`,
            body,
        })
        return result
    },
})

const CdpFunctionsRearrangePartialUpdateSchema = HogFunctionsRearrangePartialUpdateBody

const cdpFunctionsRearrangePartialUpdate = (): ToolBase<
    typeof CdpFunctionsRearrangePartialUpdateSchema,
    Schemas.HogFunction[]
> => ({
    name: 'cdp-functions-rearrange-partial-update',
    schema: CdpFunctionsRearrangePartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsRearrangePartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.orders !== undefined) {
            body['orders'] = params.orders
        }
        const result = await context.api.request<Schemas.HogFunction[]>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/rearrange/`,
            body,
        })
        return result
    },
})

const CdpFunctionsRestoreRevisionSchema = HogFunctionsRevisionsRestoreCreateParams.omit({ project_id: true }).extend(
    HogFunctionsRevisionsRestoreCreateBody.shape
)

const cdpFunctionsRestoreRevision = (): ToolBase<typeof CdpFunctionsRestoreRevisionSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-restore-revision',
    schema: CdpFunctionsRestoreRevisionSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsRestoreRevisionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.overwrite !== undefined) {
            body['overwrite'] = params.overwrite
        }
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/revisions/${encodeURIComponent(String(params.version))}/restore/`,
            body,
        })
        return result
    },
})

const CdpFunctionsRetrieveSchema = HogFunctionsRetrieveParams.omit({ project_id: true })

const cdpFunctionsRetrieve = (): ToolBase<typeof CdpFunctionsRetrieveSchema, Schemas.HogFunction> => ({
    name: 'cdp-functions-retrieve',
    schema: CdpFunctionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CdpFunctionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFunction>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_functions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cdp-functions-create': cdpFunctionsCreate,
    'cdp-functions-delete': cdpFunctionsDelete,
    'cdp-functions-discard-draft': cdpFunctionsDiscardDraft,
    'cdp-functions-get-revision': cdpFunctionsGetRevision,
    'cdp-functions-invocations-create': cdpFunctionsInvocationsCreate,
    'cdp-functions-list': cdpFunctionsList,
    'cdp-functions-list-revisions': cdpFunctionsListRevisions,
    'cdp-functions-logs-retrieve': cdpFunctionsLogsRetrieve,
    'cdp-functions-metrics-retrieve': cdpFunctionsMetricsRetrieve,
    'cdp-functions-partial-update': cdpFunctionsPartialUpdate,
    'cdp-functions-publish': cdpFunctionsPublish,
    'cdp-functions-rearrange-partial-update': cdpFunctionsRearrangePartialUpdate,
    'cdp-functions-restore-revision': cdpFunctionsRestoreRevision,
    'cdp-functions-retrieve': cdpFunctionsRetrieve,
}
