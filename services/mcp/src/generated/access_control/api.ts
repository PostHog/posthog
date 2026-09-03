/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Object rules that apply to everyone without a rule of their own on that object.
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
 * Property rules that apply to everyone without a rule of their own on that property.
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
 * The project's default access: the level everyone without a rule of their own gets for the project and for each resource type, plus the resource types that accept rules on single objects.
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
 * Object rules configured for one member: the dashboards, insights, notebooks and other single objects the member is granted or denied, regardless of the resource-level rules.
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
 * Property rules configured for one member: the person and event properties the member can read, read and write, or not see.
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
 * Every organization member's resolved access to this project and to each resource type in it: the member's own rule, the level that is enforced, and the rule the enforced level comes from (their own, a role's, the project default, or an org-admin bypass). Pass `member_id` for one member.
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
 * Object rules configured for one role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
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
 * Property rules configured for one role: the person and event properties the role's members can read, read and write, or not see.
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
