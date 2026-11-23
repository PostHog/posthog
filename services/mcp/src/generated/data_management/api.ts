/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const EventSchemasCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const EventSchemasCreateBody = () => zod.object({
    event_definition: zod.string(),
    property_group_id: zod.string(),
})

export const SchemaPropertyGroupsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const schemaPropertyGroupsCreateBodyNameMax = 400

export const schemaPropertyGroupsCreateBodyPropertiesItemNameMax = 400

export const SchemaPropertyGroupsCreateBody = () => zod.object({
    name: zod.string().max(schemaPropertyGroupsCreateBodyNameMax),
    description: zod.string().optional(),
    properties: zod
        .array(
            zod.object({
                id: zod.string().optional(),
                name: zod.string().max(schemaPropertyGroupsCreateBodyPropertiesItemNameMax),
                property_type: zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Object', 'Array'])
                    .describe(
                        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Object` - Object\n\* `Array` - Array'
                    ),
                is_required: zod.boolean().optional(),
                is_optional_in_types: zod.boolean().optional(),
                description: zod.string().optional(),
                created_at: zod.iso.datetime({ offset: true }).optional(),
                updated_at: zod.iso.datetime({ offset: true }).optional(),
            })
        )
        .optional(),
})
