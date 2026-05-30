/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Get all property access control rules for a property definition.
 */
export const PropertyAccessControlsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PropertyAccessControlsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    property_definition_id: zod.string().describe('The property definition ID to fetch access control rules for.'),
})

/**
 * Create or update a property access control rule.
 */
export const PropertyAccessControlsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PropertyAccessControlsCreateBody = /* @__PURE__ */ zod
    .object({
        property_definition_id: zod.string().describe('The property definition ID this rule applies to.'),
        access_level: zod
            .enum(['read_write', 'read', 'none'])
            .describe('* `read_write` - read_write\n* `read` - read\n* `none` - none')
            .describe(
                'The access level to set for this rule.\n\n* `read_write` - read_write\n* `read` - read\n* `none` - none'
            ),
        organization_member: zod.uuid().nullish().describe('The organization member UUID to set an override for.'),
        role: zod.uuid().nullish().describe('The role UUID to set an override for.'),
    })
    .describe('Request body for upserting a rule (create or update).')

/**
 * Delete a property access control rule. The rule is identified by `property_definition_id` plus an optional `organization_member` or `role` query parameter. Omitting both targets deletes the default rule.
 */
export const PropertyAccessControlsDestroyParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PropertyAccessControlsDestroyQueryParams = /* @__PURE__ */ zod.object({
    organization_member: zod
        .string()
        .optional()
        .describe('The organization member UUID whose override should be deleted.'),
    property_definition_id: zod.string().describe('The property definition ID the rule applies to.'),
    role: zod.string().optional().describe('The role UUID whose override should be deleted.'),
})
