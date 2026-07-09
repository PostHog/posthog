/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * @summary Create a streamlit app
 */
export const StreamlitAppsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().describe('Name of the app.'),
    description: zod.string().optional().describe('Optional description of the app.'),
    cpu_cores: zod.number().optional().describe('CPU cores allocated to the sandbox.'),
    memory_gb: zod.number().optional().describe('Memory in GB allocated to the sandbox.'),
})

/**
 * @summary Update a streamlit app
 */
export const StreamlitAppsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Partially update a streamlit app
 */
export const StreamlitAppsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Activate an existing app version
 */
export const StreamlitAppsActivateVersionCreateBody = /* @__PURE__ */ zod.object({
    version_number: zod
        .number()
        .describe('Version number to activate. Must reference an existing version of this app.'),
})

/**
 * @summary Upload a new app version
 */
export const StreamlitAppsUploadVersionCreateBody = /* @__PURE__ */ zod.object({
    file: zod.url().describe('Zip archive containing the Streamlit app sources (max 10 MB).'),
})
