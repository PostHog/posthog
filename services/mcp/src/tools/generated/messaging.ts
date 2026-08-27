// AUTO-GENERATED from products/messaging/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    MessagingPreferencesBulkAddOptOutsCreateBody,
    MessagingPreferencesOptOutsRetrieveQueryParams,
    MessagingPreferencesRemoveOptOutCreateBody,
} from '@/generated/messaging/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const OptOutsAddSchema = MessagingPreferencesBulkAddOptOutsCreateBody

const optOutsAdd = (): ToolBase<typeof OptOutsAddSchema, Schemas.BulkAddOptOutsResult> => ({
    name: 'opt-outs-add',
    schema: OptOutsAddSchema,
    handler: async (context: Context, params: z.infer<typeof OptOutsAddSchema>) => {
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

const OptOutsListSchema = MessagingPreferencesOptOutsRetrieveQueryParams

const optOutsList = (): ToolBase<typeof OptOutsListSchema, Schemas.PaginatedOptOuts> => ({
    name: 'opt-outs-list',
    schema: OptOutsListSchema,
    handler: async (context: Context, params: z.infer<typeof OptOutsListSchema>) => {
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

const OptOutsRemoveSchema = MessagingPreferencesRemoveOptOutCreateBody

const optOutsRemove = (): ToolBase<typeof OptOutsRemoveSchema, Schemas.MessagePreferences> => ({
    name: 'opt-outs-remove',
    schema: OptOutsRemoveSchema,
    handler: async (context: Context, params: z.infer<typeof OptOutsRemoveSchema>) => {
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
    'opt-outs-add': optOutsAdd,
    'opt-outs-list': optOutsList,
    'opt-outs-remove': optOutsRemove,
}
