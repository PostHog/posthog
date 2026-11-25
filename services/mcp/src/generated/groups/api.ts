/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL.
 * To get a list of valid group types, call /api/:project_id/groups_types/.
 *
 * Uses forward-only keyset pagination via the `cursor` parameter.
 * The `previous` field in the response envelope is always null.
 */
export const GroupsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const GroupsListQueryParams = () => zod.object({
    cursor: zod.string().optional().describe('Pagination cursor returned in the `next` URL of a previous response'),
    group_key: zod.string().optional().describe('Filter groups whose key contains this string (case-insensitive)'),
    group_type_index: zod.number().describe('Specify the group type to list'),
    search: zod.string().optional().describe('Search the group name'),
})

export const GroupsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const groupsCreateBodyGroupTypeIndexMin = -2147483648
export const groupsCreateBodyGroupTypeIndexMax = 2147483647

export const groupsCreateBodyGroupKeyMax = 400

export const GroupsCreateBody = () => zod.object({
    group_type_index: zod.number().min(groupsCreateBodyGroupTypeIndexMin).max(groupsCreateBodyGroupTypeIndexMax),
    group_key: zod.string().max(groupsCreateBodyGroupKeyMax),
    group_properties: zod.unknown().optional(),
})

export const GroupsDeletePropertyCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const GroupsDeletePropertyCreateQueryParams = () => zod.object({
    group_key: zod.string().describe('Specify the key of the group to find'),
    group_type_index: zod.number().describe('Specify the group type to find'),
})

export const GroupsDeletePropertyCreateBody = () => zod.object({
    $unset: zod.string().describe('Name of the property to delete.'),
})

export const GroupsFindRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const GroupsFindRetrieveQueryParams = () => zod.object({
    group_key: zod.string().describe('Specify the key of the group to find'),
    group_type_index: zod.number().describe('Specify the group type to find'),
    skip_create_notebook: zod
        .boolean()
        .optional()
        .describe(
            "When true, do not lazily create the group's CRM notebook. Use for read-only lookups (e.g. resolving a group's display name) that should not have side effects."
        ),
})

export const GroupsUpdatePropertyCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const GroupsUpdatePropertyCreateQueryParams = () => zod.object({
    group_key: zod.string().describe('Specify the key of the group to find'),
    group_type_index: zod.number().describe('Specify the group type to find'),
})

export const GroupsUpdatePropertyCreateBody = () => zod.object({
    key: zod.string().describe('Name of the property to set.'),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean(), zod.looseObject({}), zod.array(zod.unknown())])
        .describe('Value to set. Any JSON value other than null.'),
})

export const GroupsTypesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
