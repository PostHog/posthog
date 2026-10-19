// AUTO-GENERATED from products/research_desk/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/research_desk/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ResearchDeskContactCheckSchema = () => {
    const ResearchDeskContactCheckListQueryParams = orvalSchemas.ResearchDeskContactCheckListQueryParams()
    return ResearchDeskContactCheckListQueryParams
}

const researchDeskContactCheck = (): ToolBase<
    ReturnType<typeof ResearchDeskContactCheckSchema>,
    Schemas.ContactCheckResult[]
> => ({
    name: 'research-desk-contact-check',
    schema: ResearchDeskContactCheckSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ResearchDeskContactCheckSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ContactCheckResult[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/research_desk/contact_check/`,
            query: {
                domain: params.domain,
                emails: params.emails,
                lookback_days: params.lookback_days,
                warn_within_days: params.warn_within_days,
            },
        })
        return result
    },
})

const ResearchDeskSessionsListSchema = () => {
    const ResearchDeskSessionsListQueryParams = orvalSchemas.ResearchDeskSessionsListQueryParams()
    return ResearchDeskSessionsListQueryParams
}

const researchDeskSessionsList = (): ToolBase<
    ReturnType<typeof ResearchDeskSessionsListSchema>,
    WithPostHogUrl<Schemas.ResearchSessionDTO[]>
> => ({
    name: 'research-desk-sessions-list',
    schema: ResearchDeskSessionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ResearchDeskSessionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ResearchSessionDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/research_desk/sessions/`,
            query: {
                start_after: params.start_after,
                start_before: params.start_before,
            },
        })
        return await withPostHogUrl(context, result, '/')
    },
})

const ResearchDeskSourcesListSchema = () => z.object({})

const researchDeskSourcesList = (): ToolBase<
    ReturnType<typeof ResearchDeskSourcesListSchema>,
    WithPostHogUrl<Schemas.ResearchSourceDTO[]>
> => ({
    name: 'research-desk-sources-list',
    schema: ResearchDeskSourcesListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof ResearchDeskSourcesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ResearchSourceDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/research_desk/sources/`,
        })
        return await withPostHogUrl(context, result, '/')
    },
})

const ResearchDeskSourcesCreateSchema = () => {
    const ResearchDeskSourcesCreateBody = orvalSchemas.ResearchDeskSourcesCreateBody()
    return ResearchDeskSourcesCreateBody
}

const researchDeskSourcesCreate = (): ToolBase<
    ReturnType<typeof ResearchDeskSourcesCreateSchema>,
    Schemas.ResearchSourceDTO
> => ({
    name: 'research-desk-sources-create',
    schema: ResearchDeskSourcesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ResearchDeskSourcesCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.external_id !== undefined) {
            body['external_id'] = params.external_id
        }
        if (params.label !== undefined) {
            body['label'] = params.label
        }
        if (params.owner_email !== undefined) {
            body['owner_email'] = params.owner_email
        }
        if (params.product_area !== undefined) {
            body['product_area'] = params.product_area
        }
        const result = await context.api.request<Schemas.ResearchSourceDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/research_desk/sources/`,
            body,
        })
        return result
    },
})

const ResearchDeskSourcesUpdateSchema = () => {
    const ResearchDeskSourcesPartialUpdateBody = orvalSchemas.ResearchDeskSourcesPartialUpdateBody()
    const ResearchDeskSourcesPartialUpdateParams = orvalSchemas.ResearchDeskSourcesPartialUpdateParams()
    return ResearchDeskSourcesPartialUpdateParams.omit({ project_id: true }).extend(
        ResearchDeskSourcesPartialUpdateBody.shape
    )
}

const researchDeskSourcesUpdate = (): ToolBase<
    ReturnType<typeof ResearchDeskSourcesUpdateSchema>,
    Schemas.ResearchSourceDTO
> => ({
    name: 'research-desk-sources-update',
    schema: ResearchDeskSourcesUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ResearchDeskSourcesUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.label !== undefined) {
            body['label'] = params.label
        }
        if (params.owner_email !== undefined) {
            body['owner_email'] = params.owner_email
        }
        if (params.product_area !== undefined) {
            body['product_area'] = params.product_area
        }
        if (params.active !== undefined) {
            body['active'] = params.active
        }
        const result = await context.api.request<Schemas.ResearchSourceDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/research_desk/sources/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'research-desk-contact-check': researchDeskContactCheck,
    'research-desk-sessions-list': researchDeskSessionsList,
    'research-desk-sources-list': researchDeskSourcesList,
    'research-desk-sources-create': researchDeskSourcesCreate,
    'research-desk-sources-update': researchDeskSourcesUpdate,
}
