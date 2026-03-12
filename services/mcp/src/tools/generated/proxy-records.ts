// AUTO-GENERATED from services/mcp/definitions/proxy-records.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ProxyRecordsCreateBody,
    ProxyRecordsDestroyParams,
    ProxyRecordsListQueryParams,
    ProxyRecordsRetrieveParams,
    ProxyRecordsRetryCreateParams,
} from '@/generated/proxy-records/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ProxyListSchema = ProxyRecordsListQueryParams

const proxyList = (): ToolBase<typeof ProxyListSchema, Schemas.PaginatedProxyRecordList & { _posthogUrl: string }> => ({
    name: 'proxy-list',
    schema: ProxyListSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyListSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.PaginatedProxyRecordList>({
            method: 'GET',
            path: `/api/organizations/${orgId}/proxy_records/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl('@current')}/settings/organization-proxy`,
        }
    },
})

const ProxyGetSchema = ProxyRecordsRetrieveParams.omit({ organization_id: true })

const proxyGet = (): ToolBase<typeof ProxyGetSchema, Schemas.ProxyRecord> => ({
    name: 'proxy-get',
    schema: ProxyGetSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyGetSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'GET',
            path: `/api/organizations/${orgId}/proxy_records/${params.id}/`,
        })
        return result
    },
})

const ProxyCreateSchema = ProxyRecordsCreateBody

const proxyCreate = (): ToolBase<typeof ProxyCreateSchema, Schemas.ProxyRecord> => ({
    name: 'proxy-create',
    schema: ProxyCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyCreateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${orgId}/proxy_records/`,
            body,
        })
        return result
    },
})

const ProxyRetrySchema = ProxyRecordsRetryCreateParams.omit({ organization_id: true })

const proxyRetry = (): ToolBase<typeof ProxyRetrySchema, Schemas.ProxyRecord> => ({
    name: 'proxy-retry',
    schema: ProxyRetrySchema,
    handler: async (context: Context, params: z.infer<typeof ProxyRetrySchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${orgId}/proxy_records/${params.id}/retry/`,
        })
        return result
    },
})

const ProxyDeleteSchema = ProxyRecordsDestroyParams.omit({ organization_id: true })

const proxyDelete = (): ToolBase<typeof ProxyDeleteSchema, unknown> => ({
    name: 'proxy-delete',
    schema: ProxyDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof ProxyDeleteSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/organizations/${orgId}/proxy_records/${params.id}/`,
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
