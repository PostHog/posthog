/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LlmSkillsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmSkillsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to skill names and descriptions.'),
})

export const LlmSkillsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmSkillsCreateBodyNameMax = 64

export const llmSkillsCreateBodyDescriptionMax = 4096

export const llmSkillsCreateBodyLicenseMax = 255

export const llmSkillsCreateBodyCompatibilityMax = 500

export const llmSkillsCreateBodyFilesItemPathMax = 500

export const llmSkillsCreateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsCreateBodyFilesItemContentTypeMax = 100

export const LlmSkillsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(llmSkillsCreateBodyNameMax)
            .describe('Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.'),
        description: zod
            .string()
            .max(llmSkillsCreateBodyDescriptionMax)
            .describe('What this skill does and when to use it. Max 4096 characters.'),
        body: zod.string().describe('The SKILL.md instruction content (markdown).'),
        license: zod
            .string()
            .max(llmSkillsCreateBodyLicenseMax)
            .optional()
            .describe('License name or reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(llmSkillsCreateBodyCompatibilityMax)
            .optional()
            .describe('Environment requirements (intended product, system packages, network access, etc.).'),
        allowed_tools: zod.array(zod.string()).optional().describe('List of pre-approved tools the skill may use.'),
        metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
        files: zod
            .array(
                zod.object({
                    path: zod
                        .string()
                        .max(llmSkillsCreateBodyFilesItemPathMax)
                        .describe(
                            "File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'."
                        ),
                    content: zod.string().describe('Text content of the file.'),
                    content_type: zod
                        .string()
                        .max(llmSkillsCreateBodyFilesItemContentTypeMax)
                        .default(llmSkillsCreateBodyFilesItemContentTypeDefault)
                        .describe('MIME type of the file content.'),
                })
            )
            .optional()
            .describe('Bundled files to include with the initial version (scripts, references, assets).'),
    })
    .describe('Create serializer — accepts bundled files as write-only input on POST.')

export const llmSkillsNameRetrievePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameRetrievePathSkillNameRegExp),
})

export const LlmSkillsNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific skill version to fetch. If omitted, the latest version is returned.'),
})

export const llmSkillsNamePartialUpdatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNamePartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNamePartialUpdatePathSkillNameRegExp),
})

export const llmSkillsNamePartialUpdateBodyDescriptionMax = 4096

export const llmSkillsNamePartialUpdateBodyLicenseMax = 255

export const llmSkillsNamePartialUpdateBodyCompatibilityMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemPathMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax = 100

export const LlmSkillsNamePartialUpdateBody = /* @__PURE__ */ zod.object({
    body: zod
        .string()
        .optional()
        .describe(
            'Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits.'
        ),
    edits: zod
        .array(
            zod.object({
                old: zod.string().describe('Text to find in the current skill body. Must match exactly once.'),
                new: zod.string().describe('Replacement text.'),
            })
        )
        .optional()
        .describe(
            "List of find/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body."
        ),
    description: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyDescriptionMax)
        .optional()
        .describe('Updated description for the new version.'),
    license: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyLicenseMax)
        .optional()
        .describe('License name or reference.'),
    compatibility: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyCompatibilityMax)
        .optional()
        .describe('Environment requirements.'),
    allowed_tools: zod.array(zod.string()).optional().describe('List of pre-approved tools the skill may use.'),
    metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
    files: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemPathMax)
                    .describe("File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'."),
                content: zod.string().describe('Text content of the file.'),
                content_type: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax)
                    .default(llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault)
                    .describe('MIME type of the file content.'),
            })
        )
        .optional()
        .describe('Bundled files to include with this version. Replaces all files from the previous version.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmSkillsNameDuplicateCreatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameDuplicateCreatePathSkillNameRegExp),
})

export const llmSkillsNameDuplicateCreateBodyNewNameMax = 64

export const LlmSkillsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmSkillsNameDuplicateCreateBodyNewNameMax)
        .describe('Name for the duplicated skill. Must be unique.'),
})

export const llmSkillsNameFilesRetrievePathFilePathRegExp = new RegExp('^.+$')
export const llmSkillsNameFilesRetrievePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameFilesRetrieveParams = /* @__PURE__ */ zod.object({
    file_path: zod.string().regex(llmSkillsNameFilesRetrievePathFilePathRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameFilesRetrievePathSkillNameRegExp),
})

export const LlmSkillsNameFilesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific skill version to fetch. If omitted, the latest version is returned.'),
})
