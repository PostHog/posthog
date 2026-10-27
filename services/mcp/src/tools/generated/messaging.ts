// AUTO-GENERATED from products/messaging/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/messaging/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MessageCategoriesCreateSchema = () => {
    const MessagingCategoriesCreateBody = orvalSchemas.MessagingCategoriesCreateBody()
    return MessagingCategoriesCreateBody
}

const messageCategoriesCreate = (): ToolBase<
    ReturnType<typeof MessageCategoriesCreateSchema>,
    Schemas.MessageCategory
> => ({
    name: 'message-categories-create',
    schema: MessageCategoriesCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessageCategoriesCreateSchema>>) => {
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

const MessageCategoriesGetSchema = () => {
    const MessagingCategoriesRetrieveParams = orvalSchemas.MessagingCategoriesRetrieveParams()
    return MessagingCategoriesRetrieveParams.omit({ project_id: true })
}

const messageCategoriesGet = (): ToolBase<ReturnType<typeof MessageCategoriesGetSchema>, Schemas.MessageCategory> => ({
    name: 'message-categories-get',
    schema: MessageCategoriesGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessageCategoriesGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MessageCategory>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const MessageCategoriesListSchema = () => {
    const MessagingCategoriesListQueryParams = orvalSchemas.MessagingCategoriesListQueryParams()
    return MessagingCategoriesListQueryParams
}

const messageCategoriesList = (): ToolBase<
    ReturnType<typeof MessageCategoriesListSchema>,
    WithPostHogUrl<Schemas.PaginatedMessageCategoryList>
> => ({
    name: 'message-categories-list',
    schema: MessageCategoriesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessageCategoriesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMessageCategoryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/messaging_categories/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/workflows')
    },
})

const MessageCategoriesUpdateSchema = () => {
    const MessagingCategoriesPartialUpdateBody = orvalSchemas.MessagingCategoriesPartialUpdateBody()
    const MessagingCategoriesPartialUpdateParams = orvalSchemas.MessagingCategoriesPartialUpdateParams()
    return MessagingCategoriesPartialUpdateParams.omit({ project_id: true }).extend(
        MessagingCategoriesPartialUpdateBody.shape
    )
}

const messageCategoriesUpdate = (): ToolBase<
    ReturnType<typeof MessageCategoriesUpdateSchema>,
    Schemas.MessageCategory
> => ({
    name: 'message-categories-update',
    schema: MessageCategoriesUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MessageCategoriesUpdateSchema>>) => {
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
    'message-categories-create': messageCategoriesCreate,
    'message-categories-get': messageCategoriesGet,
    'message-categories-list': messageCategoriesList,
    'message-categories-update': messageCategoriesUpdate,
    'opt-outs-add': optOutsAdd,
    'opt-outs-list': optOutsList,
    'opt-outs-remove': optOutsRemove,
}
