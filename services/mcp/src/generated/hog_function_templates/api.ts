/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFunctionTemplatesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionTemplatesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const hogFunctionTemplatesListResponseResultsItemNameMax = 400

export const hogFunctionTemplatesListResponseResultsItemCodeLanguageMax = 20

export const hogFunctionTemplatesListResponseResultsItemTypeMax = 50

export const hogFunctionTemplatesListResponseResultsItemStatusMax = 20

export const HogFunctionTemplatesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFunctionTemplatesListResponseResultsItemNameMax),
            description: zod.string().nullish(),
            code: zod.string(),
            code_language: zod.string().max(hogFunctionTemplatesListResponseResultsItemCodeLanguageMax).optional(),
            inputs_schema: zod.unknown(),
            type: zod.string().max(hogFunctionTemplatesListResponseResultsItemTypeMax),
            status: zod.string().max(hogFunctionTemplatesListResponseResultsItemStatusMax).optional(),
            category: zod.unknown().optional(),
            free: zod.boolean().optional(),
            icon_url: zod.string().nullish(),
            filters: zod.unknown().nullish(),
            masking: zod.unknown().nullish(),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string(),
                        include_by_default: zod.boolean().nullish(),
                        filters: zod.unknown().nullish(),
                        inputs: zod.unknown().nullish(),
                        inputs_schema: zod.unknown().nullish(),
                    })
                )
                .nullish(),
        })
    ),
})

export const HogFunctionTemplatesRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    template_id: zod.string(),
})

export const hogFunctionTemplatesRetrieveResponseNameMax = 400

export const hogFunctionTemplatesRetrieveResponseCodeLanguageMax = 20

export const hogFunctionTemplatesRetrieveResponseTypeMax = 50

export const hogFunctionTemplatesRetrieveResponseStatusMax = 20

export const HogFunctionTemplatesRetrieveResponse = zod.object({
    id: zod.string(),
    name: zod.string().max(hogFunctionTemplatesRetrieveResponseNameMax),
    description: zod.string().nullish(),
    code: zod.string(),
    code_language: zod.string().max(hogFunctionTemplatesRetrieveResponseCodeLanguageMax).optional(),
    inputs_schema: zod.unknown(),
    type: zod.string().max(hogFunctionTemplatesRetrieveResponseTypeMax),
    status: zod.string().max(hogFunctionTemplatesRetrieveResponseStatusMax).optional(),
    category: zod.unknown().optional(),
    free: zod.boolean().optional(),
    icon_url: zod.string().nullish(),
    filters: zod.unknown().nullish(),
    masking: zod.unknown().nullish(),
    mapping_templates: zod
        .array(
            zod.object({
                name: zod.string(),
                include_by_default: zod.boolean().nullish(),
                filters: zod.unknown().nullish(),
                inputs: zod.unknown().nullish(),
                inputs_schema: zod.unknown().nullish(),
            })
        )
        .nullish(),
})
