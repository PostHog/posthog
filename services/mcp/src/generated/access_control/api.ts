/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Object rules that apply to everyone in the project without a rule of their own on that object.
 */
export const organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Property rules that apply to everyone in the project without a rule of their own on that property.
 */
export const organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Set or clear the rule everyone in the project gets for a scope, unless a member or role rule of their own applies. The scope is the project (`resource: project`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlDefaultRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlDefaultRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlDefaultRulesUpdateBody = () => zod
    .object({
        resource: zod
            .string()
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
    })
    .describe('A rule for everyone in the project without a member or role rule of their own.')

/**
 * The project's default access. Returns the level that applies to the project and to each resource type when a member or a role has no rule of their own. Also lists the resource types that accept rules on single objects, with the levels such a rule can set.
 */
export const organizationsProjectsAccessControlDefaultsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Object rules configured for a member: the single objects, for example a dashboard or a notebook, the member is granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlMemberObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMemberObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams = () => zod.object({
    member_id: zod
        .string()
        .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
})

/**
 * Property rules configured for a member: the person and event properties the member can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams = () => zod.object({
    member_id: zod
        .string()
        .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
})

/**
 * Set or clear one member's rule for a scope. A member rule applies to that person only and takes precedence over their role rules and the default. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlMemberRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlMemberRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberRulesUpdateBody = () => zod
    .object({
        resource: zod
            .string()
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        member_id: zod
            .string()
            .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
    })
    .describe('A rule for one organization member.')

/**
 * Every organization member's access in this project. For the project and for each resource type, the response gives the member's own rule and the level that is enforced. It also says where the enforced level comes from: the member's rule, a role's rule, the project default, or full access as an organization admin. Pass `member_id` for one member.
 */
export const organizationsProjectsAccessControlMembersRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMembersRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMembersRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMembersRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMembersRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMembersRetrieveQueryParams = () => zod.object({
    member_id: zod.string().optional().describe('Narrow the list to one organization membership id.'),
})

/**
 * Object rules configured for a role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlRoleObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRoleObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRoleObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRoleObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRoleObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams = () => zod.object({
    role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
})

/**
 * Property rules configured for a role: the person and event properties the role's members can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlRolePropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRolePropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRolePropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRolePropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRolePropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams = () => zod.object({
    role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
})

/**
 * Set or clear one role's rule for a scope. A role rule applies to every member of the role and takes precedence over the default. Requires the role-based access feature. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlRoleRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlRoleRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRoleRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRoleRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlRoleRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRoleRulesUpdateBody = () => zod
    .object({
        resource: zod
            .string()
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
    })
    .describe('A rule for every member of one role.')

/**
 * Every role's resolved access to this project and to each resource type in it: the role's own rule, the level that is enforced, and the rule the enforced level comes from. Pass `role_id` for one role.
 */
export const organizationsProjectsAccessControlRolesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRolesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRolesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRolesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRolesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRolesRetrieveQueryParams = () => zod.object({
    role_id: zod.string().optional().describe('Narrow the list to one role.'),
})
