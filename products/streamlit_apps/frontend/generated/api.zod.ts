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

export const streamlitAppsActivateVersionCreateBodyNameMax = 255

export const StreamlitAppsActivateVersionCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(streamlitAppsActivateVersionCreateBodyNameMax),
    description: zod.string().optional(),
    cpu_cores: zod.number().optional(),
    memory_gb: zod.number().optional(),
})

/**
 * Create a new version from a single free-text app.py source string.
 *
 * The agent-friendly alternative to a multipart zip upload: pass the app's
 * Python source (and optionally requirements.txt contents) as plain text.
 */
export const StreamlitAppsCreateVersionFromSourceCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .describe(
            "Full Python source for the Streamlit app's root app.py file, as free text. Becomes a new version and is set as the active version."
        ),
    requirements: zod
        .string()
        .optional()
        .describe(
            'Optional requirements.txt contents (one pip requirement per line). Currently informational — the sandbox base image ships the common data stack.'
        ),
})

export const streamlitAppsUploadVersionCreateBodyNameMax = 255

export const StreamlitAppsUploadVersionCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(streamlitAppsUploadVersionCreateBodyNameMax),
    description: zod.string().optional(),
    cpu_cores: zod.number().optional(),
    memory_gb: zod.number().optional(),
})
