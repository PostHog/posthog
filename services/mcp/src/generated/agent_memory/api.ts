/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the team's memory files (metadata only, no bodies).
 */
export const AgentMemoryListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentMemoryListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    prefix: zod
        .string()
        .optional()
        .describe("Only return files whose path starts with this fragment, e.g. 'scouts/' or 'users/'."),
})

/**
 * Append or replace a single markdown section atomically — never clobbers concurrent edits.
 */
export const AgentMemoryAppendCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentMemoryAppendCreateBodyPathMax = 1024

export const agentMemoryAppendCreateBodyHeadingMax = 500

export const agentMemoryAppendCreateBodyBodyMax = 1000000

export const agentMemoryAppendCreateBodyUpdatedByRunMax = 255

export const AgentMemoryAppendCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentMemoryAppendCreateBodyPathMax)
        .describe("Relative path of the file to append to, e.g. 'project.md'. Created if it does not exist."),
    heading: zod
        .string()
        .max(agentMemoryAppendCreateBodyHeadingMax)
        .describe(
            "Section title (without leading '#'). If a section with this title already exists, its body is replaced; otherwise a new '## {heading}' section is appended."
        ),
    body: zod
        .string()
        .max(agentMemoryAppendCreateBodyBodyMax)
        .describe('Markdown body for the section. Never clobbers other sections of the file.'),
    updated_by_run: zod
        .string()
        .max(agentMemoryAppendCreateBodyUpdatedByRunMax)
        .nullish()
        .describe(
            "Optional identifier of the agent run performing this write (e.g. a scout run UUID), recorded for attribution. Omit for human/API writes; the writer's user is attributed automatically."
        ),
})

/**
 * Read a single memory file by path.
 */
export const AgentMemoryReadRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentMemoryReadRetrieveQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe("Relative path of the file to read, e.g. 'project.md'."),
})

/**
 * Compare-and-set write of a whole file. Returns 409 on a version mismatch.
 */
export const AgentMemoryWriteCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentMemoryWriteCreateBodyPathMax = 1024

export const agentMemoryWriteCreateBodyContentMax = 1000000

export const agentMemoryWriteCreateBodyUpdatedByRunMax = 255

export const AgentMemoryWriteCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentMemoryWriteCreateBodyPathMax)
        .describe(
            "Relative path of the file to write, e.g. 'project.md' or 'users/jane-doe.md'. Must end in '.md', may not contain '..' or absolute segments."
        ),
    content: zod
        .string()
        .max(agentMemoryWriteCreateBodyContentMax)
        .describe(
            "Full markdown body to store. Replaces the file's content entirely — prefer the append endpoint to add a section without clobbering concurrent edits."
        ),
    expected_version: zod
        .number()
        .nullish()
        .describe(
            'Compare-and-set token. Omit (or null) to create a new file; pass the version you last read to update an existing one. A mismatch returns 409 — re-read and merge before retrying.'
        ),
    updated_by_run: zod
        .string()
        .max(agentMemoryWriteCreateBodyUpdatedByRunMax)
        .nullish()
        .describe(
            "Optional identifier of the agent run performing this write (e.g. a scout run UUID), recorded for attribution. Omit for human/API writes; the writer's user is attributed automatically."
        ),
})
