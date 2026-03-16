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
    template_id: zod
        .string()
        .optional()
        .describe(
            'Filter to a specific template by its template_id. Deprecated templates are excluded from list results; use the retrieve endpoint to look up a template by ID regardless of status.'
        ),
    type: zod
        .string()
        .optional()
        .describe(
            'Filter by template type (e.g. destination, email, sms_provider, broadcast). Defaults to destination if neither type nor types is provided.'
        ),
    types: zod
        .string()
        .optional()
        .describe('Comma-separated list of template types to include (e.g. destination,email,sms_provider).'),
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
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
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
    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
    name: zod.string().max(hogFunctionTemplatesRetrieveResponseNameMax).describe('Display name of the template.'),
    description: zod.string().nullish().describe('What this template does.'),
    code: zod.string().describe('Source code of the template.'),
    code_language: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseCodeLanguageMax)
        .optional()
        .describe("Programming language: 'hog' or 'javascript'."),
    inputs_schema: zod
        .unknown()
        .describe('Schema defining configurable inputs for functions created from this template.'),
    type: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseTypeMax)
        .describe('Function type this template creates.'),
    status: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseStatusMax)
        .optional()
        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
    free: zod.boolean().optional().describe('Whether available on free plans.'),
    icon_url: zod.string().nullish().describe("URL for the template's icon."),
    filters: zod.unknown().nullish().describe('Default event filters.'),
    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
    mapping_templates: zod
        .array(
            zod.object({
                name: zod.string().describe('Name of this mapping template.'),
                include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                inputs_schema: zod
                    .unknown()
                    .nullish()
                    .describe('Additional input schema fields specific to this mapping.'),
            })
        )
        .nullish()
        .describe('Pre-defined mapping configurations for destination templates.'),
})
