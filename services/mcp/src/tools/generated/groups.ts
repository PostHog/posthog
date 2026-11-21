// AUTO-GENERATED from products/groups/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/groups/api'
import hooks_groupsFind from '@/tools/groups/findGroupHooks'
import { withToolHooks } from '@/tools/tool-hooks'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const GroupsCreateSchema = () => {
    const GroupsCreateBody = orvalSchemas.GroupsCreateBody()
    return GroupsCreateBody
}

const groupsCreate = (): ToolBase<ReturnType<typeof GroupsCreateSchema>, Schemas.Group> => ({
    name: 'groups-create',
    schema: GroupsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof GroupsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.group_type_index !== undefined) {
            body['group_type_index'] = params.group_type_index
        }
        if (params.group_key !== undefined) {
            body['group_key'] = params.group_key
        }
        if (params.group_properties !== undefined) {
            body['group_properties'] = params.group_properties
        }
        const result = await context.api.request<Schemas.Group>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups/`,
            body,
        })
        return result
    },
})

const GroupsDeletePropertySchema = () => {
    const GroupsDeletePropertyCreateBody = orvalSchemas.GroupsDeletePropertyCreateBody()
    const GroupsDeletePropertyCreateQueryParams = orvalSchemas.GroupsDeletePropertyCreateQueryParams()
    return GroupsDeletePropertyCreateQueryParams.extend(GroupsDeletePropertyCreateBody.shape)
        .omit({ $unset: true })
        .extend({ property_name: GroupsDeletePropertyCreateBody.shape['$unset'] })
}

const groupsDeleteProperty = (): ToolBase<ReturnType<typeof GroupsDeletePropertySchema>, Schemas.Group> => ({
    name: 'groups-delete-property',
    schema: GroupsDeletePropertySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof GroupsDeletePropertySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.property_name !== undefined) {
            body['$unset'] = params.property_name
        }
        const result = await context.api.request<Schemas.Group>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups/delete_property/`,
            body,
            query: {
                group_key: params.group_key,
                group_type_index: params.group_type_index,
            },
        })
        return result
    },
})

const GroupsFindSchema = () => {
    const GroupsFindRetrieveQueryParams = orvalSchemas.GroupsFindRetrieveQueryParams()
    return GroupsFindRetrieveQueryParams.extend({
        skip_create_notebook: GroupsFindRetrieveQueryParams.shape['skip_create_notebook'].default(true).optional(),
    })
}

const groupsFind = (): ToolBase<ReturnType<typeof GroupsFindSchema>, Schemas.FindGroup> => ({
    name: 'groups-find',
    schema: GroupsFindSchema(),
    handler: withToolHooks(
        hooks_groupsFind,
        async (context: Context, params: z.infer<ReturnType<typeof GroupsFindSchema>>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.FindGroup>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/groups/find/`,
                query: {
                    group_key: params.group_key,
                    group_type_index: params.group_type_index,
                    skip_create_notebook: params.skip_create_notebook,
                },
            })
            return result
        }
    ),
})

const GroupsListSchema = () => {
    const GroupsListQueryParams = orvalSchemas.GroupsListQueryParams()
    return GroupsListQueryParams
}

const groupsList = (): ToolBase<ReturnType<typeof GroupsListSchema>, Schemas.Group[]> => ({
    name: 'groups-list',
    schema: GroupsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof GroupsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Group[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups/`,
            query: {
                cursor: params.cursor,
                group_key: params.group_key,
                group_type_index: params.group_type_index,
                search: params.search,
            },
        })
        return result
    },
})

const GroupsTypesListSchema = () => z.object({})

const groupsTypesList = (): ToolBase<
    ReturnType<typeof GroupsTypesListSchema>,
    WithPostHogUrl<Schemas.GroupType[]>
> => ({
    name: 'groups-types-list',
    schema: GroupsTypesListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof GroupsTypesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GroupType[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/`,
        })
        return await withPostHogUrl(context, result, '/groups')
    },
})

const GroupsUpdatePropertySchema = () => {
    const GroupsUpdatePropertyCreateBody = orvalSchemas.GroupsUpdatePropertyCreateBody()
    const GroupsUpdatePropertyCreateQueryParams = orvalSchemas.GroupsUpdatePropertyCreateQueryParams()
    return GroupsUpdatePropertyCreateQueryParams.extend(GroupsUpdatePropertyCreateBody.shape)
}

const groupsUpdateProperty = (): ToolBase<ReturnType<typeof GroupsUpdatePropertySchema>, Schemas.Group> => ({
    name: 'groups-update-property',
    schema: GroupsUpdatePropertySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof GroupsUpdatePropertySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.value !== undefined) {
            body['value'] = params.value
        }
        const result = await context.api.request<Schemas.Group>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups/update_property/`,
            body,
            query: {
                group_key: params.group_key,
                group_type_index: params.group_type_index,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'groups-create': groupsCreate,
    'groups-delete-property': groupsDeleteProperty,
    'groups-find': groupsFind,
    'groups-list': groupsList,
    'groups-types-list': groupsTypesList,
    'groups-update-property': groupsUpdateProperty,
}
