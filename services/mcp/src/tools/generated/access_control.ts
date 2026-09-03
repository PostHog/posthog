// AUTO-GENERATED from products/access_control/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/access_control/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AccessControlDefaultsGetSchema = () => {
    const OrganizationsProjectsAccessControlDefaultsRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlDefaultsRetrieveParams()
    return OrganizationsProjectsAccessControlDefaultsRetrieveParams.omit({ organization_id: true }).extend({
        id: OrganizationsProjectsAccessControlDefaultsRetrieveParams.shape['id']
            .describe('Project id. If omitted, uses the active project.')
            .optional(),
    })
}

const accessControlDefaultsGet = (): ToolBase<
    ReturnType<typeof AccessControlDefaultsGetSchema>,
    Schemas.AccessControlDefaultsResponse
> => ({
    name: 'access-control-defaults-get',
    schema: AccessControlDefaultsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlDefaultsGetSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlDefaultsResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_defaults/`,
        })
        return result
    },
})

const AccessControlMembersListSchema = () => {
    const OrganizationsProjectsAccessControlMembersRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlMembersRetrieveParams()
    const OrganizationsProjectsAccessControlMembersRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlMembersRetrieveQueryParams()
    return OrganizationsProjectsAccessControlMembersRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlMembersRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlMembersRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            member_id: OrganizationsProjectsAccessControlMembersRetrieveQueryParams.shape['member_id'].describe(
                'Optional. Narrow the result to one member, by organization membership id.'
            ),
        })
}

const accessControlMembersList = (): ToolBase<
    ReturnType<typeof AccessControlMembersListSchema>,
    Schemas.AccessControlMembersResponse
> => ({
    name: 'access-control-members-list',
    schema: AccessControlMembersListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlMembersListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlMembersResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_members/`,
            query: {
                member_id: params.member_id,
            },
        })
        return result
    },
})

const AccessControlRolesListSchema = () => {
    const OrganizationsProjectsAccessControlRolesRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlRolesRetrieveParams()
    const OrganizationsProjectsAccessControlRolesRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlRolesRetrieveQueryParams()
    return OrganizationsProjectsAccessControlRolesRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlRolesRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlRolesRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            role_id: OrganizationsProjectsAccessControlRolesRetrieveQueryParams.shape['role_id'].describe(
                'Optional. Narrow the result to one role, by role id.'
            ),
        })
}

const accessControlRolesList = (): ToolBase<
    ReturnType<typeof AccessControlRolesListSchema>,
    Schemas.AccessControlRolesResponse
> => ({
    name: 'access-control-roles-list',
    schema: AccessControlRolesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlRolesListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlRolesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_roles/`,
            query: {
                role_id: params.role_id,
            },
        })
        return result
    },
})

const AccessControlDefaultObjectsListSchema = () => {
    const OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams()
    return OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams.omit({ organization_id: true }).extend({
        id: OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams.shape['id']
            .describe('Project id. If omitted, uses the active project.')
            .optional(),
    })
}

const accessControlDefaultObjectsList = (): ToolBase<
    ReturnType<typeof AccessControlDefaultObjectsListSchema>,
    Schemas.AccessControlObjectRulesResponse
> => ({
    name: 'access-control-default-objects-list',
    schema: AccessControlDefaultObjectsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlDefaultObjectsListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlObjectRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_default_objects/`,
        })
        return result
    },
})

const AccessControlDefaultPropertiesListSchema = () => {
    const OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams()
    return OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams.omit({ organization_id: true }).extend({
        id: OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams.shape['id']
            .describe('Project id. If omitted, uses the active project.')
            .optional(),
    })
}

const accessControlDefaultPropertiesList = (): ToolBase<
    ReturnType<typeof AccessControlDefaultPropertiesListSchema>,
    Schemas.AccessControlPropertyRulesResponse
> => ({
    name: 'access-control-default-properties-list',
    schema: AccessControlDefaultPropertiesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlDefaultPropertiesListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlPropertyRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_default_properties/`,
        })
        return result
    },
})

const AccessControlMemberObjectsListSchema = () => {
    const OrganizationsProjectsAccessControlMemberObjectsRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlMemberObjectsRetrieveParams()
    const OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams()
    return OrganizationsProjectsAccessControlMemberObjectsRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlMemberObjectsRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            member_id: OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams.shape['member_id'].describe(
                'The organization membership id, as `organization_membership_id` in access-control-members-list.'
            ),
        })
}

const accessControlMemberObjectsList = (): ToolBase<
    ReturnType<typeof AccessControlMemberObjectsListSchema>,
    Schemas.AccessControlObjectRulesResponse
> => ({
    name: 'access-control-member-objects-list',
    schema: AccessControlMemberObjectsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlMemberObjectsListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlObjectRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_member_objects/`,
            query: {
                member_id: params.member_id,
            },
        })
        return result
    },
})

const AccessControlMemberPropertiesListSchema = () => {
    const OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams()
    const OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams()
    return OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            member_id: OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams.shape[
                'member_id'
            ].describe(
                'The organization membership id, as `organization_membership_id` in access-control-members-list.'
            ),
        })
}

const accessControlMemberPropertiesList = (): ToolBase<
    ReturnType<typeof AccessControlMemberPropertiesListSchema>,
    Schemas.AccessControlPropertyRulesResponse
> => ({
    name: 'access-control-member-properties-list',
    schema: AccessControlMemberPropertiesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlMemberPropertiesListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlPropertyRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_member_properties/`,
            query: {
                member_id: params.member_id,
            },
        })
        return result
    },
})

const AccessControlRoleObjectsListSchema = () => {
    const OrganizationsProjectsAccessControlRoleObjectsRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlRoleObjectsRetrieveParams()
    const OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams()
    return OrganizationsProjectsAccessControlRoleObjectsRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlRoleObjectsRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            role_id: OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams.shape['role_id'].describe(
                'The role id, as `role_id` in access-control-roles-list or roles-list.'
            ),
        })
}

const accessControlRoleObjectsList = (): ToolBase<
    ReturnType<typeof AccessControlRoleObjectsListSchema>,
    Schemas.AccessControlObjectRulesResponse
> => ({
    name: 'access-control-role-objects-list',
    schema: AccessControlRoleObjectsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlRoleObjectsListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlObjectRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_role_objects/`,
            query: {
                role_id: params.role_id,
            },
        })
        return result
    },
})

const AccessControlRolePropertiesListSchema = () => {
    const OrganizationsProjectsAccessControlRolePropertiesRetrieveParams =
        orvalSchemas.OrganizationsProjectsAccessControlRolePropertiesRetrieveParams()
    const OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams =
        orvalSchemas.OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams()
    return OrganizationsProjectsAccessControlRolePropertiesRetrieveParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams.shape)
        .extend({
            id: OrganizationsProjectsAccessControlRolePropertiesRetrieveParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            role_id: OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams.shape['role_id'].describe(
                'The role id, as `role_id` in access-control-roles-list or roles-list.'
            ),
        })
}

const accessControlRolePropertiesList = (): ToolBase<
    ReturnType<typeof AccessControlRolePropertiesListSchema>,
    Schemas.AccessControlPropertyRulesResponse
> => ({
    name: 'access-control-role-properties-list',
    schema: AccessControlRolePropertiesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlRolePropertiesListSchema>>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.AccessControlPropertyRulesResponse>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_role_properties/`,
            query: {
                role_id: params.role_id,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'access-control-defaults-get': accessControlDefaultsGet,
    'access-control-members-list': accessControlMembersList,
    'access-control-roles-list': accessControlRolesList,
    'access-control-default-objects-list': accessControlDefaultObjectsList,
    'access-control-default-properties-list': accessControlDefaultPropertiesList,
    'access-control-member-objects-list': accessControlMemberObjectsList,
    'access-control-member-properties-list': accessControlMemberPropertiesList,
    'access-control-role-objects-list': accessControlRoleObjectsList,
    'access-control-role-properties-list': accessControlRolePropertiesList,
}
