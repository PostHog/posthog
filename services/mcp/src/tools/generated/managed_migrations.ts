// AUTO-GENERATED from products/managed_migrations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/managed_migrations/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ManagedMigrationsSupportGetSchema = () => {
    const ManagedMigrationsSupportRetrieveParams = orvalSchemas.ManagedMigrationsSupportRetrieveParams()
    return ManagedMigrationsSupportRetrieveParams
}

const managedMigrationsSupportGet = (): ToolBase<
    ReturnType<typeof ManagedMigrationsSupportGetSchema>,
    Schemas.BatchImportSupportDetail
> => ({
    name: 'managed-migrations-support-get',
    schema: ManagedMigrationsSupportGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ManagedMigrationsSupportGetSchema>>) => {
        const result = await context.api.request<Schemas.BatchImportSupportDetail>({
            method: 'GET',
            path: `/api/managed_migrations_support/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ManagedMigrationsSupportListSchema = () => {
    const ManagedMigrationsSupportListQueryParams = orvalSchemas.ManagedMigrationsSupportListQueryParams()
    return ManagedMigrationsSupportListQueryParams
}

const managedMigrationsSupportList = (): ToolBase<
    ReturnType<typeof ManagedMigrationsSupportListSchema>,
    WithPostHogUrl<Schemas.PaginatedBatchImportSupportListList>
> => ({
    name: 'managed-migrations-support-list',
    schema: ManagedMigrationsSupportListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ManagedMigrationsSupportListSchema>>) => {
        const result = await context.api.request<Schemas.PaginatedBatchImportSupportListList>({
            method: 'GET',
            path: `/api/managed_migrations_support/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                search: params.search,
                status: params.status,
                team_id: params.team_id,
            },
        })
        return await withPostHogUrl(context, result, '/managed_migrations')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'managed-migrations-support-get': managedMigrationsSupportGet,
    'managed-migrations-support-list': managedMigrationsSupportList,
}
