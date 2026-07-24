// AUTO-GENERATED from products/cookie_banner/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    CookieBannerCreateBody,
    CookieBannerListQueryParams,
    CookieBannerPartialUpdateBody,
    CookieBannerPartialUpdateParams,
} from '@/generated/cookie_banner/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CookieBannerCreateSchema = CookieBannerCreateBody

const cookieBannerCreate = (): ToolBase<typeof CookieBannerCreateSchema, Schemas.CookieBannerConfig> => ({
    name: 'cookie-banner-create',
    schema: CookieBannerCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CookieBannerCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.appearance !== undefined) {
            body['appearance'] = params.appearance
        }
        const result = await context.api.request<Schemas.CookieBannerConfig>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cookie_banner/`,
            body,
        })
        return result
    },
})

const CookieBannerListSchema = CookieBannerListQueryParams

const cookieBannerList = (): ToolBase<
    typeof CookieBannerListSchema,
    WithPostHogUrl<Schemas.PaginatedCookieBannerConfigList>
> => ({
    name: 'cookie-banner-list',
    schema: CookieBannerListSchema,
    handler: async (context: Context, params: z.infer<typeof CookieBannerListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCookieBannerConfigList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cookie_banner/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/cookie-banner')
    },
})

const CookieBannerPartialUpdateSchema = CookieBannerPartialUpdateParams.omit({ project_id: true }).extend(
    CookieBannerPartialUpdateBody.shape
)

const cookieBannerPartialUpdate = (): ToolBase<typeof CookieBannerPartialUpdateSchema, Schemas.CookieBannerConfig> => ({
    name: 'cookie-banner-partial-update',
    schema: CookieBannerPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CookieBannerPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.appearance !== undefined) {
            body['appearance'] = params.appearance
        }
        const result = await context.api.request<Schemas.CookieBannerConfig>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cookie_banner/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cookie-banner-create': cookieBannerCreate,
    'cookie-banner-list': cookieBannerList,
    'cookie-banner-partial-update': cookieBannerPartialUpdate,
}
