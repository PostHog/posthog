/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * @summary List streamlit apps
 */
export const StreamlitAppsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StreamlitAppsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * @summary Create a streamlit app
 */
export const StreamlitAppsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StreamlitAppsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().describe('Name of the app.'),
    description: zod.string().optional().describe('Optional description of the app.'),
    cpu_cores: zod.number().optional().describe('CPU cores allocated to the sandbox.'),
    memory_gb: zod.number().optional().describe('Memory in GB allocated to the sandbox.'),
})

/**
 * @summary Retrieve a streamlit app
 */
export const StreamlitAppsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Partially update a streamlit app
 */
export const StreamlitAppsPartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const StreamlitAppsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Delete a streamlit app
 */
export const StreamlitAppsDestroyParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Create an app version from source code
 */
export const StreamlitAppsCreateVersionFromSourceCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const streamlitAppsCreateVersionFromSourceCreateBodySourceMax = 1048576

export const StreamlitAppsCreateVersionFromSourceCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .max(streamlitAppsCreateVersionFromSourceCreateBodySourceMax)
        .describe(
            "Full Python source for the Streamlit app's root app.py file, as free text (max 1 MB). Becomes a new version and is set as the active version."
        ),
})

/**
 * @summary Start the app sandbox
 */
export const StreamlitAppsStartCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Get app sandbox status
 */
export const StreamlitAppsStatusRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Stop the app sandbox
 */
export const StreamlitAppsStopCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary List app versions
 */
export const StreamlitAppsVersionsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})
