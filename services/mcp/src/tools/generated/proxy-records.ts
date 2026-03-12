// AUTO-GENERATED from services/mcp/definitions/proxy-records.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ProxyRecordsCreateBody,
    ProxyRecordsCreateParams,
    ProxyRecordsDestroyParams,
    ProxyRecordsListParams,
    ProxyRecordsListQueryParams,
    ProxyRecordsRetrieveParams,
    ProxyRecordsRetryCreateBody,
    ProxyRecordsRetryCreateParams,
} from '@/generated/proxy-records/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ProxyListSchema = ProxyRecordsListParams.omit({ project_id: true }).extend(ProxyRecordsListQueryParams.shape)

const proxyList = (): ToolBase<typeof ProxyListSchema, Schemas.PaginatedProxyRecordList & { _posthogUrl: string }> => ({
    name: 'proxy-list',
    schema: ProxyListSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedProxyRecordList>({
            method: 'GET',
            path: `/api/organizations/${params.organization_id}/proxy_records/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/organization-proxy`,
        }
    },
})

const ProxyGetSchema = ProxyRecordsRetrieveParams.omit({ project_id: true })

const proxyGet = (): ToolBase<typeof ProxyGetSchema, Schemas.ProxyRecord> => ({
    name: 'proxy-get',
    schema: ProxyGetSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyGetSchema>) => {
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'GET',
            path: `/api/organizations/${params.organization_id}/proxy_records/${params.id}/`,
        })
        return result
    },
})

const ProxyCreateSchema = ProxyRecordsCreateParams.omit({ project_id: true }).extend(ProxyRecordsCreateBody.shape)

const proxyCreate = (): ToolBase<typeof ProxyCreateSchema, Schemas.ProxyRecord> => ({
    name: 'proxy-create',
    schema: ProxyCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyCreateSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${params.organization_id}/proxy_records/`,
            body,
        })
        return result
    },
})

const ProxyRetrySchema = ProxyRecordsRetryCreateParams.omit({ project_id: true }).extend(
    ProxyRecordsRetryCreateBody.shape
)

const proxyRetry = (): ToolBase<typeof ProxyRetrySchema, Schemas.ProxyRecord> => ({
    name: 'proxy-retry',
    schema: ProxyRetrySchema,
    handler: async (context: Context, params: z.infer<typeof ProxyRetrySchema>) => {
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${params.organization_id}/proxy_records/${params.id}/retry/`,
            body,
        })
        return result
    },
})

const ProxyDeleteSchema = ProxyRecordsDestroyParams.omit({ project_id: true })

const proxyDelete = (): ToolBase<typeof ProxyDeleteSchema, unknown> => ({
    name: 'proxy-delete',
    schema: ProxyDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyDeleteSchema>) => {
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/organizations/${params.organization_id}/proxy_records/${params.id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'proxy-list': proxyList,
    'proxy-get': proxyGet,
    'proxy-create': proxyCreate,
    'proxy-retry': proxyRetry,
    'proxy-delete': proxyDelete,
}
