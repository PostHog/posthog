// AUTO-GENERATED from products/access_control/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/access_control/api'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
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

const AccessControlDefaultRuleSetSchema = () => {
    const OrganizationsProjectsAccessControlDefaultRulesUpdateBody =
        orvalSchemas.OrganizationsProjectsAccessControlDefaultRulesUpdateBody()
    const OrganizationsProjectsAccessControlDefaultRulesUpdateParams =
        orvalSchemas.OrganizationsProjectsAccessControlDefaultRulesUpdateParams()
    return OrganizationsProjectsAccessControlDefaultRulesUpdateParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlDefaultRulesUpdateBody.shape)
        .extend({
            id: OrganizationsProjectsAccessControlDefaultRulesUpdateParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            resource: OrganizationsProjectsAccessControlDefaultRulesUpdateBody.shape['resource'].describe(
                'The scope: `project`, a tool name such as `dashboard` or `feature_flag`, or `property_definition`. The tool names are the keys of `resource_access_levels` on access-control-defaults-get.'
            ),
            resource_id: OrganizationsProjectsAccessControlDefaultRulesUpdateBody.shape['resource_id']
                .default(null)
                .optional()
                .describe(
                    "The project id for a project rule, the object's id for a rule on one object (a pk, as returned by the object's own get tool), or the property definition id for a property rule. Null only for a rule on a whole tool."
                ),
            access_level: OrganizationsProjectsAccessControlDefaultRulesUpdateBody.shape['access_level'].describe(
                "The level to set, within the scope's `minimum` and `maximum` on access-control-defaults-get, or null to remove the rule."
            ),
        })
}

const AccessControlDefaultRuleSetSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const accessControlDefaultRuleSetPrepare = (): ToolBase<
    ReturnType<typeof AccessControlDefaultRuleSetSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'access-control-default-rule-set-prepare',
    schema: AccessControlDefaultRuleSetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlDefaultRuleSetSchema>>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        return await prepareConfirmedAction(context, {
            args: { ...params, id },
            purpose: 'access-control-default-rule-set',
            actionLabel: 'change the default access rule',
            messageTemplate:
                "About to set the default {resource} access rule in project {id} to {access_level}, for object {resource_id} (null means the whole tool; a null level clears the rule). This changes what every member without a rule of their own gets. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { orgId: String(__scopeOrgId) },
        })
    },
})

const accessControlDefaultRuleSetExecute = (): ToolBase<
    typeof AccessControlDefaultRuleSetSchemaExecute,
    WithAgentNote<Schemas.AccessControlStoredRule>
> => ({
    name: 'access-control-default-rule-set-execute',
    schema: AccessControlDefaultRuleSetSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof AccessControlDefaultRuleSetSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const __guard = await executeConfirmedAction<z.infer<ReturnType<typeof AccessControlDefaultRuleSetSchema>>>(
            context,
            {
                incomingArgs: confirmationParams,
                purpose: 'access-control-default-rule-set',
                codec: __runtime.codec,
                ledger: __runtime.ledger,
                stash: __runtime.stash,
                expectedScope: { orgId: String(__scopeOrgId) },
            }
        )
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const orgId = __scopeOrgId
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const body: Record<string, unknown> = {}
        if (params.resource !== undefined) {
            body['resource'] = params.resource
        }
        if (params.resource_id !== undefined) {
            body['resource_id'] = params.resource_id
        }
        if (params.access_level !== undefined) {
            body['access_level'] = params.access_level
        }
        const result = await context.api.request<Schemas.AccessControlStoredRule>({
            method: 'PUT',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_default_rules/`,
            body,
        })
        return withAgentNote(
            result,
            'A member rule or a role rule on the same scope still wins over this default. Verify the result with access-control-defaults-get or access-control-members-list.\n'
        )
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
            "The member's tool-level access and their `role_ids` are on access-control-members-list. Object rules from the member's roles are on access-control-role-objects-list, one call per role id.\n"
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
            "Property rules from the member's roles are on access-control-role-properties-list, one call per id in the member's `role_ids` from access-control-members-list. Rules for everyone in the project are on access-control-default-properties-list.\n"
        )
    },
})

const AccessControlMemberRuleSetSchema = () => {
    const OrganizationsProjectsAccessControlMemberRulesUpdateBody =
        orvalSchemas.OrganizationsProjectsAccessControlMemberRulesUpdateBody()
    const OrganizationsProjectsAccessControlMemberRulesUpdateParams =
        orvalSchemas.OrganizationsProjectsAccessControlMemberRulesUpdateParams()
    return OrganizationsProjectsAccessControlMemberRulesUpdateParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlMemberRulesUpdateBody.shape)
        .extend({
            id: OrganizationsProjectsAccessControlMemberRulesUpdateParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            member_id: OrganizationsProjectsAccessControlMemberRulesUpdateBody.shape['member_id'].describe(
                'The organization membership id, as `organization_membership_id` in access-control-members-list.'
            ),
            resource: OrganizationsProjectsAccessControlMemberRulesUpdateBody.shape['resource'].describe(
                'The scope: `project`, a tool name such as `dashboard` or `feature_flag`, or `property_definition`. The tool names are the keys of `resources` in access-control-members-list.'
            ),
            resource_id: OrganizationsProjectsAccessControlMemberRulesUpdateBody.shape['resource_id']
                .default(null)
                .optional()
                .describe(
                    "The project id for a project rule, the object's id for a rule on one object (a pk, as returned by the object's own get tool), or the property definition id for a property rule. Null only for a rule on a whole tool."
                ),
            access_level: OrganizationsProjectsAccessControlMemberRulesUpdateBody.shape['access_level'].describe(
                "The level to set, within the scope's `minimum` and `maximum` on access-control-defaults-get, or null to remove the rule."
            ),
        })
}

const AccessControlMemberRuleSetSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const accessControlMemberRuleSetPrepare = (): ToolBase<
    ReturnType<typeof AccessControlMemberRuleSetSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'access-control-member-rule-set-prepare',
    schema: AccessControlMemberRuleSetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlMemberRuleSetSchema>>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        return await prepareConfirmedAction(context, {
            args: { ...params, id },
            purpose: 'access-control-member-rule-set',
            actionLabel: "change a member's access rule",
            messageTemplate:
                "About to set the {resource} access rule for member {member_id} in project {id} to {access_level}, for object {resource_id} (null means the whole tool; a null level clears the rule). Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { orgId: String(__scopeOrgId) },
        })
    },
})

const accessControlMemberRuleSetExecute = (): ToolBase<
    typeof AccessControlMemberRuleSetSchemaExecute,
    WithAgentNote<Schemas.AccessControlStoredRule>
> => ({
    name: 'access-control-member-rule-set-execute',
    schema: AccessControlMemberRuleSetSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof AccessControlMemberRuleSetSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const __guard = await executeConfirmedAction<z.infer<ReturnType<typeof AccessControlMemberRuleSetSchema>>>(
            context,
            {
                incomingArgs: confirmationParams,
                purpose: 'access-control-member-rule-set',
                codec: __runtime.codec,
                ledger: __runtime.ledger,
                stash: __runtime.stash,
                expectedScope: { orgId: String(__scopeOrgId) },
            }
        )
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const orgId = __scopeOrgId
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const body: Record<string, unknown> = {}
        if (params.resource !== undefined) {
            body['resource'] = params.resource
        }
        if (params.resource_id !== undefined) {
            body['resource_id'] = params.resource_id
        }
        if (params.access_level !== undefined) {
            body['access_level'] = params.access_level
        }
        if (params.member_id !== undefined) {
            body['member_id'] = params.member_id
        }
        const result = await context.api.request<Schemas.AccessControlStoredRule>({
            method: 'PUT',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_member_rules/`,
            body,
        })
        return withAgentNote(
            result,
            'Organization admins and owners have full access regardless of rules. Verify the result with access-control-members-list and `member_id`.\n'
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
            'For a question about one object, for example a dashboard or a table, call access-control-member-objects-list; for a person or event property, access-control-member-properties-list. Rules a role sets on objects or properties are only on the role-objects and role-properties tools. Level bounds per tool are on access-control-defaults-get.\n'
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
                'The role id, as `role_id` in access-control-roles-list or an entry of `role_ids` in access-control-members-list.'
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
                'The role id, as `role_id` in access-control-roles-list or an entry of `role_ids` in access-control-members-list.'
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

const AccessControlRoleRuleSetSchema = () => {
    const OrganizationsProjectsAccessControlRoleRulesUpdateBody =
        orvalSchemas.OrganizationsProjectsAccessControlRoleRulesUpdateBody()
    const OrganizationsProjectsAccessControlRoleRulesUpdateParams =
        orvalSchemas.OrganizationsProjectsAccessControlRoleRulesUpdateParams()
    return OrganizationsProjectsAccessControlRoleRulesUpdateParams.omit({ organization_id: true })
        .extend(OrganizationsProjectsAccessControlRoleRulesUpdateBody.shape)
        .extend({
            id: OrganizationsProjectsAccessControlRoleRulesUpdateParams.shape['id']
                .describe('Project id. If omitted, uses the active project.')
                .optional(),
            role_id: OrganizationsProjectsAccessControlRoleRulesUpdateBody.shape['role_id'].describe(
                'The role id, as `role_id` in access-control-roles-list or `id` in roles-list.'
            ),
            resource: OrganizationsProjectsAccessControlRoleRulesUpdateBody.shape['resource'].describe(
                'The scope: `project`, a tool name such as `dashboard` or `feature_flag`, or `property_definition`. The tool names are the keys of `resources` in access-control-roles-list.'
            ),
            resource_id: OrganizationsProjectsAccessControlRoleRulesUpdateBody.shape['resource_id']
                .default(null)
                .optional()
                .describe(
                    "The project id for a project rule, the object's id for a rule on one object (a pk, as returned by the object's own get tool), or the property definition id for a property rule. Null only for a rule on a whole tool."
                ),
            access_level: OrganizationsProjectsAccessControlRoleRulesUpdateBody.shape['access_level'].describe(
                "The level to set, within the scope's `minimum` and `maximum` on access-control-defaults-get, or null to remove the rule."
            ),
        })
}

const AccessControlRoleRuleSetSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const accessControlRoleRuleSetPrepare = (): ToolBase<
    ReturnType<typeof AccessControlRoleRuleSetSchema>,
    PrepareConfirmedActionResult
> => ({
    name: 'access-control-role-rule-set-prepare',
    schema: AccessControlRoleRuleSetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AccessControlRoleRuleSetSchema>>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        return await prepareConfirmedAction(context, {
            args: { ...params, id },
            purpose: 'access-control-role-rule-set',
            actionLabel: "change a role's access rule",
            messageTemplate:
                "About to set the {resource} access rule for role {role_id} in project {id} to {access_level}, for object {resource_id} (null means the whole tool; a null level clears the rule). This affects every member of the role. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { orgId: String(__scopeOrgId) },
        })
    },
})

const accessControlRoleRuleSetExecute = (): ToolBase<
    typeof AccessControlRoleRuleSetSchemaExecute,
    WithAgentNote<Schemas.AccessControlStoredRule>
> => ({
    name: 'access-control-role-rule-set-execute',
    schema: AccessControlRoleRuleSetSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof AccessControlRoleRuleSetSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeOrgId = await context.stateManager.getOrgID()
        const __guard = await executeConfirmedAction<z.infer<ReturnType<typeof AccessControlRoleRuleSetSchema>>>(
            context,
            {
                incomingArgs: confirmationParams,
                purpose: 'access-control-role-rule-set',
                codec: __runtime.codec,
                ledger: __runtime.ledger,
                stash: __runtime.stash,
                expectedScope: { orgId: String(__scopeOrgId) },
            }
        )
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const orgId = __scopeOrgId
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const body: Record<string, unknown> = {}
        if (params.resource !== undefined) {
            body['resource'] = params.resource
        }
        if (params.resource_id !== undefined) {
            body['resource_id'] = params.resource_id
        }
        if (params.access_level !== undefined) {
            body['access_level'] = params.access_level
        }
        if (params.role_id !== undefined) {
            body['role_id'] = params.role_id
        }
        const result = await context.api.request<Schemas.AccessControlStoredRule>({
            method: 'PUT',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/access_control_role_rules/`,
            body,
        })
        return withAgentNote(
            result,
            'Who is in the role is on role-members-list. Verify the result with access-control-roles-list and `role_id`.\n'
        )
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
            "A member's enforced level already includes their roles, so for a person use access-control-members-list. For a role's rules on one object or property, call access-control-role-objects-list or access-control-role-properties-list. A member's roles are `role_ids` on access-control-members-list, and role-members-list gives who is in a role.\n"
        )
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'access-control-default-objects-list': accessControlDefaultObjectsList,
    'access-control-default-properties-list': accessControlDefaultPropertiesList,
    'access-control-default-rule-set-prepare': accessControlDefaultRuleSetPrepare,
    'access-control-default-rule-set-execute': accessControlDefaultRuleSetExecute,
    'access-control-defaults-get': accessControlDefaultsGet,
    'access-control-member-objects-list': accessControlMemberObjectsList,
    'access-control-member-properties-list': accessControlMemberPropertiesList,
    'access-control-member-rule-set-prepare': accessControlMemberRuleSetPrepare,
    'access-control-member-rule-set-execute': accessControlMemberRuleSetExecute,
    'access-control-members-list': accessControlMembersList,
    'access-control-role-objects-list': accessControlRoleObjectsList,
    'access-control-role-properties-list': accessControlRolePropertiesList,
    'access-control-role-rule-set-prepare': accessControlRoleRuleSetPrepare,
    'access-control-role-rule-set-execute': accessControlRoleRuleSetExecute,
    'access-control-roles-list': accessControlRolesList,
}
