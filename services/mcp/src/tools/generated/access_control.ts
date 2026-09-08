// AUTO-GENERATED from products/access_control/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/access_control/api'
import {
    withPostHogUrl,
    withAgentNote,
    omitResponseFields,
    type WithPostHogUrl,
    type WithAgentNote,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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
    WithPostHogUrl<Schemas.AccessControlObjectRulesResponse>
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
        return await withPostHogUrl(context, result, '/settings/environment-access-control')
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
    WithPostHogUrl<Schemas.AccessControlPropertyRulesResponse>
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
        return await withPostHogUrl(context, result, '/settings/environment-access-control')
    },
})

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
    WithAgentNote<Schemas.AccessControlDefaultsResponse>
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
        const filtered = omitResponseFields(result, ['can_edit']) as typeof result
        return withAgentNote(
            filtered,
            'access-control-members-list or access-control-roles-list show who deviates from this baseline. access-control-default-objects-list and access-control-default-properties-list show defaults set on single objects or properties.\n'
        )
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
    WithAgentNote<WithPostHogUrl<Schemas.AccessControlObjectRulesResponse>>
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
        return withAgentNote(
            await withPostHogUrl(context, result, '/settings/environment-access-control'),
            "The member's tool-level access is on access-control-members-list. Object rules from the member's roles are on access-control-role-objects-list, one call per role from role-members-list.\n"
        )
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
    WithAgentNote<WithPostHogUrl<Schemas.AccessControlPropertyRulesResponse>>
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
        return withAgentNote(
            await withPostHogUrl(context, result, '/settings/environment-access-control'),
            "Property rules from the member's roles are on access-control-role-properties-list, one call per role from role-members-list. Rules for everyone are on access-control-default-properties-list.\n"
        )
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
    WithAgentNote<WithPostHogUrl<Schemas.AccessControlMembersResponse>>
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
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, [
                    'project.minimum',
                    'project.maximum',
                    'resources.*.minimum',
                    'resources.*.maximum',
                ])
            ),
        } as typeof result
        return withAgentNote(
            await withPostHogUrl(context, filtered, '/settings/environment-access-control'),
            'For one dashboard, insight, notebook or table, call access-control-member-objects-list; for a person or event property, access-control-member-properties-list. Rules a role sets on objects or properties are only on the role-objects and role-properties tools. Level bounds per tool are on access-control-defaults-get.\n'
        )
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
    WithPostHogUrl<Schemas.AccessControlObjectRulesResponse>
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
        return await withPostHogUrl(context, result, '/settings/environment-access-control')
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
    WithPostHogUrl<Schemas.AccessControlPropertyRulesResponse>
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
        return await withPostHogUrl(context, result, '/settings/environment-access-control')
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
    WithAgentNote<WithPostHogUrl<Schemas.AccessControlRolesResponse>>
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
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, [
                    'project.minimum',
                    'project.maximum',
                    'resources.*.minimum',
                    'resources.*.maximum',
                ])
            ),
        } as typeof result
        return withAgentNote(
            await withPostHogUrl(context, filtered, '/settings/environment-access-control'),
            "A member's enforced level already includes their roles, so for a person use access-control-members-list. For a role's rules on one object or property, call access-control-role-objects-list or access-control-role-properties-list. roles-list gives role ids and role-members-list gives who is in a role.\n"
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'access-control-default-objects-list': accessControlDefaultObjectsList,
    'access-control-default-properties-list': accessControlDefaultPropertiesList,
    'access-control-defaults-get': accessControlDefaultsGet,
    'access-control-member-objects-list': accessControlMemberObjectsList,
    'access-control-member-properties-list': accessControlMemberPropertiesList,
    'access-control-members-list': accessControlMembersList,
    'access-control-role-objects-list': accessControlRoleObjectsList,
    'access-control-role-properties-list': accessControlRolePropertiesList,
    'access-control-roles-list': accessControlRolesList,
}
