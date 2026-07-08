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

export const streamlitAppsCreateBodyNameMax = 255

export const StreamlitAppsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(streamlitAppsCreateBodyNameMax),
    description: zod.string().optional(),
    cpu_cores: zod.number().optional(),
    memory_gb: zod.number().optional(),
})

export const streamlitAppsUpdateBodyNameMax = 255

export const StreamlitAppsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(streamlitAppsUpdateBodyNameMax),
    description: zod.string().optional(),
    cpu_cores: zod.number().optional(),
    memory_gb: zod.number().optional(),
})

export const streamlitAppsPartialUpdateBodyNameMax = 255

export const StreamlitAppsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(streamlitAppsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    cpu_cores: zod.number().optional(),
    memory_gb: zod.number().optional(),
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
