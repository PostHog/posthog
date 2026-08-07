// AUTO-GENERATED from products/messaging/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    MessagingPreferencesBulkAddOptOutsCreateBody,
    MessagingPreferencesOptOutsRetrieveQueryParams,
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
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'opt-outs-add': optOutsAdd,
    'opt-outs-list': optOutsList,
}
