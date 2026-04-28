// AUTO-GENERATED from products/access_control/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { PropertyAccessControlsCreateBody, PropertyAccessControlsListQueryParams } from '@/generated/access_control/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PropertyAccessControlsListSchema = PropertyAccessControlsListQueryParams

const propertyAccessControlsList = (): ToolBase<
    typeof PropertyAccessControlsListSchema,
    Schemas.PaginatedPropertyAccessControlStateList
> => ({
    name: 'property-access-controls-list',
    schema: PropertyAccessControlsListSchema,
    handler: async (context: Context, params: z.infer<typeof PropertyAccessControlsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedPropertyAccessControlStateList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/property_access_controls/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                property_definition_id: params.property_definition_id,
            },
        })
        return result
    },
})

const PropertyAccessControlsCreateSchema = PropertyAccessControlsCreateBody

const propertyAccessControlsCreate = (): ToolBase<
    typeof PropertyAccessControlsCreateSchema,
    Schemas.PropertyAccessControlRule
> => ({
    name: 'property-access-controls-create',
    schema: PropertyAccessControlsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof PropertyAccessControlsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.property_definition_id !== undefined) {
            body['property_definition_id'] = params.property_definition_id
        }
        if (params.access_level !== undefined) {
            body['access_level'] = params.access_level
        }
        if (params.organization_member !== undefined) {
            body['organization_member'] = params.organization_member
        }
        if (params.role !== undefined) {
            body['role'] = params.role
        }
        const result = await context.api.request<Schemas.PropertyAccessControlRule>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/property_access_controls/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'property-access-controls-list': propertyAccessControlsList,
    'property-access-controls-create': propertyAccessControlsCreate,
}
