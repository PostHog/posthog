/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Full server record: tools, measured stats, per-version scores, connection instructions.
 */
export const McpRegistryServersRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Given a task, return the MCP servers most likely to do it, each with its rank rationale, real usage signal where we measure it, and ready-to-run connection instructions. One call is everything an agent needs to go from a task to a connected server.
 */
export const McpRegistryServersDiscoverRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const McpRegistryServersDiscoverRetrieveQueryParams = () => zod.object({
    intent: zod.string().describe('What the agent is trying to do, in natural language.'),
    limit: zod.number().optional().describe('Candidates to return (default 5, max 20).'),
    version: zod.string().optional().describe('Ranking version to rank candidates by.'),
})
