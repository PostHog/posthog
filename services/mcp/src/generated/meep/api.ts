/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MeepTopicsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const MeepTopicsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsSetScoutEnabledParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsSetScoutEnabledBody = () => zod.object({
    scout_id: zod.string(),
    enabled: zod.boolean(),
})

export const MeepTopicsCreateScoutParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsCreateScoutBodyNameMax = 100

export const meepTopicsCreateScoutBodyInstructionsMax = 16000

export const meepTopicsCreateScoutBodyCronMax = 100

export const MeepTopicsCreateScoutBody = () => zod.object({
    name: zod.string().max(meepTopicsCreateScoutBodyNameMax),
    instructions: zod.string().max(meepTopicsCreateScoutBodyInstructionsMax),
    cron: zod
        .string()
        .max(meepTopicsCreateScoutBodyCronMax)
        .optional()
        .describe("Optional five-field schedule in the project's timezone. Defaults to the native scout cadence."),
})
