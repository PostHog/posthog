// AUTO-GENERATED from products/access_control/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    PropertyAccessControlsCreateBody,
    PropertyAccessControlsDestroyQueryParams,
    PropertyAccessControlsRetrieveQueryParams,
} from '@/generated/access_control/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PropertyAccessControlsRetrieveSchema = PropertyAccessControlsRetrieveQueryParams

const propertyAccessControlsRetrieve = (): ToolBase<
    typeof PropertyAccessControlsRetrieveSchema,
    Schemas.PropertyAccessControlState
> => ({
    name: 'property-access-controls-retrieve',
    schema: PropertyAccessControlsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof PropertyAccessControlsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PropertyAccessControlState>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/property_access_controls/`,
            query: {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/property_access_controls/`,
            body,
        })
        return result
    },
})

const PropertyAccessControlsDestroySchema = PropertyAccessControlsDestroyQueryParams

const propertyAccessControlsDestroy = (): ToolBase<typeof PropertyAccessControlsDestroySchema, unknown> => ({
    name: 'property-access-controls-destroy',
    schema: PropertyAccessControlsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof PropertyAccessControlsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/property_access_controls/`,
            query: {
                organization_member: params.organization_member,
                property_definition_id: params.property_definition_id,
                role: params.role,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'property-access-controls-retrieve': propertyAccessControlsRetrieve,
    'property-access-controls-create': propertyAccessControlsCreate,
    'property-access-controls-destroy': propertyAccessControlsDestroy,
}
