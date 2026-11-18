// AUTO-GENERATED from services/mcp/definitions/proxy-records.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/proxy-records/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ProxyCreateSchema = () => {
    const ProxyRecordsCreateBody = orvalSchemas.ProxyRecordsCreateBody()
    return ProxyRecordsCreateBody
}

const proxyCreate = (): ToolBase<ReturnType<typeof ProxyCreateSchema>, Schemas.ProxyRecord> => ({
    name: 'proxy-create',
    schema: ProxyCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ProxyCreateSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/`,
            body,
        })
        return result
    },
})

const ProxyDeleteSchema = () => {
    const ProxyRecordsDestroyParams = orvalSchemas.ProxyRecordsDestroyParams()
    return ProxyRecordsDestroyParams.omit({ organization_id: true })
}

const proxyDelete = (): ToolBase<ReturnType<typeof ProxyDeleteSchema>, unknown> => ({
    name: 'proxy-delete',
    schema: ProxyDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ProxyDeleteSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ProxyDiagnoseSchema = () => {
    const ProxyRecordsDiagnoseCreateParams = orvalSchemas.ProxyRecordsDiagnoseCreateParams()
    return ProxyRecordsDiagnoseCreateParams.omit({ organization_id: true })
}

const proxyDiagnose = (): ToolBase<ReturnType<typeof ProxyDiagnoseSchema>, Schemas.DiagnosticReport> => ({
    name: 'proxy-diagnose',
    schema: ProxyDiagnoseSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ProxyDiagnoseSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.DiagnosticReport>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/${encodeURIComponent(String(params.id))}/diagnose/`,
        })
        return result
    },
})

const ProxyGetSchema = () => {
    const ProxyRecordsRetrieveParams = orvalSchemas.ProxyRecordsRetrieveParams()
    return ProxyRecordsRetrieveParams.omit({ organization_id: true })
}

const proxyGet = (): ToolBase<ReturnType<typeof ProxyGetSchema>, Schemas.ProxyRecord> => ({
    name: 'proxy-get',
    schema: ProxyGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ProxyGetSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ProxyListSchema = () => z.object({})

const proxyList = (): ToolBase<
    ReturnType<typeof ProxyListSchema>,
    WithPostHogUrl<Schemas.ProxyRecordListResponse>
> => ({
    name: 'proxy-list',
    schema: ProxyListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof ProxyListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProxyRecordListResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/`,
        })
        return await withPostHogUrl(context, result, '/settings/organization-proxy')
    },
})

const ProxyRetrySchema = () => {
    const ProxyRecordsRetryCreateParams = orvalSchemas.ProxyRecordsRetryCreateParams()
    return ProxyRecordsRetryCreateParams.omit({ organization_id: true })
}

const proxyRetry = (): ToolBase<ReturnType<typeof ProxyRetrySchema>, Schemas.ProxyRecord> => ({
    name: 'proxy-retry',
    schema: ProxyRetrySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ProxyRetrySchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProxyRecord>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/proxy_records/${encodeURIComponent(String(params.id))}/retry/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'proxy-create': proxyCreate,
    'proxy-delete': proxyDelete,
    'proxy-diagnose': proxyDiagnose,
    'proxy-get': proxyGet,
    'proxy-list': proxyList,
    'proxy-retry': proxyRetry,
}
