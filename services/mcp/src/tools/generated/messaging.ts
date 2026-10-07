// AUTO-GENERATED from products/messaging/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/messaging/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MessagingCategoriesCreateSchema = () => {
    const MessagingCategoriesCreateBody = orvalSchemas.MessagingCategoriesCreateBody()
    return MessagingCategoriesCreateBody
}

const messagingCategoriesCreate = (): ToolBase<
    ReturnType<typeof MessagingCategoriesCreateSchema>,
    Schemas.MessageCategory
> => ({
    name: 'messaging-categories-create',
    schema: MessagingCategoriesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessagingCategoriesCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.public_description !== undefined) {
            body['public_description'] = params.public_description
        }
        if (params.category_type !== undefined) {
            body['category_type'] = params.category_type
        }
        const result = await context.api.request<Schemas.MessageCategory>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/`,
            body,
        })
        return result
    },
})

const MessagingCategoriesListSchema = () => {
    const MessagingCategoriesListQueryParams = orvalSchemas.MessagingCategoriesListQueryParams()
    return MessagingCategoriesListQueryParams
}

const messagingCategoriesList = (): ToolBase<
    ReturnType<typeof MessagingCategoriesListSchema>,
    Schemas.PaginatedMessageCategoryList
> => ({
    name: 'messaging-categories-list',
    schema: MessagingCategoriesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessagingCategoriesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMessageCategoryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const MessagingCategoriesPartialUpdateSchema = () => {
    const MessagingCategoriesPartialUpdateBody = orvalSchemas.MessagingCategoriesPartialUpdateBody()
    const MessagingCategoriesPartialUpdateParams = orvalSchemas.MessagingCategoriesPartialUpdateParams()
    return MessagingCategoriesPartialUpdateParams.omit({ project_id: true }).extend(
        MessagingCategoriesPartialUpdateBody.shape
    )
}

const messagingCategoriesPartialUpdate = (): ToolBase<
    ReturnType<typeof MessagingCategoriesPartialUpdateSchema>,
    Schemas.MessageCategory
> => ({
    name: 'messaging-categories-partial-update',
    schema: MessagingCategoriesPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessagingCategoriesPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.public_description !== undefined) {
            body['public_description'] = params.public_description
        }
        if (params.category_type !== undefined) {
            body['category_type'] = params.category_type
        }
        const result = await context.api.request<Schemas.MessageCategory>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const MessagingCategoriesRetrieveSchema = () => {
    const MessagingCategoriesRetrieveParams = orvalSchemas.MessagingCategoriesRetrieveParams()
    return MessagingCategoriesRetrieveParams.omit({ project_id: true })
}

const messagingCategoriesRetrieve = (): ToolBase<
    ReturnType<typeof MessagingCategoriesRetrieveSchema>,
    Schemas.MessageCategory
> => ({
    name: 'messaging-categories-retrieve',
    schema: MessagingCategoriesRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessagingCategoriesRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MessageCategory>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const OptOutsAddSchema = () => {
    const MessagingPreferencesBulkAddOptOutsCreateBody = orvalSchemas.MessagingPreferencesBulkAddOptOutsCreateBody()
    return MessagingPreferencesBulkAddOptOutsCreateBody
}

const optOutsAdd = (): ToolBase<ReturnType<typeof OptOutsAddSchema>, Schemas.BulkAddOptOutsResult> => ({
    name: 'opt-outs-add',
    schema: OptOutsAddSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof OptOutsAddSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.opt_outs !== undefined) {
            body['opt_outs'] = params.opt_outs
        }
        if (params.category_key !== undefined) {
            body['category_key'] = params.category_key
        }
        const result = await context.api.request<Schemas.BulkAddOptOutsResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_preferences/bulk_add_opt_outs/`,
            body,
        })
        return result
    },
})

const OptOutsListSchema = () => {
    const MessagingPreferencesOptOutsRetrieveQueryParams = orvalSchemas.MessagingPreferencesOptOutsRetrieveQueryParams()
    return MessagingPreferencesOptOutsRetrieveQueryParams
}

const optOutsList = (): ToolBase<ReturnType<typeof OptOutsListSchema>, Schemas.PaginatedOptOuts> => ({
    name: 'opt-outs-list',
    schema: OptOutsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof OptOutsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedOptOuts>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_preferences/opt_outs/`,
            query: {
                category_key: params.category_key,
                page: params.page,
                page_size: params.page_size,
                search: params.search,
            },
        })
        return result
    },
})

const OptOutsRemoveSchema = () => {
    const MessagingPreferencesRemoveOptOutCreateBody = orvalSchemas.MessagingPreferencesRemoveOptOutCreateBody()
    return MessagingPreferencesRemoveOptOutCreateBody
}

const optOutsRemove = (): ToolBase<ReturnType<typeof OptOutsRemoveSchema>, Schemas.MessagePreferences> => ({
    name: 'opt-outs-remove',
    schema: OptOutsRemoveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof OptOutsRemoveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.identifier !== undefined) {
            body['identifier'] = params.identifier
        }
        if (params.category_key !== undefined) {
            body['category_key'] = params.category_key
        }
        const result = await context.api.request<Schemas.MessagePreferences>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_preferences/remove_opt_out/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'messaging-categories-create': messagingCategoriesCreate,
    'messaging-categories-list': messagingCategoriesList,
    'messaging-categories-partial-update': messagingCategoriesPartialUpdate,
    'messaging-categories-retrieve': messagingCategoriesRetrieve,
    'opt-outs-add': optOutsAdd,
    'opt-outs-list': optOutsList,
    'opt-outs-remove': optOutsRemove,
}
