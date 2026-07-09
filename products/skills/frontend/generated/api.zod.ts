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
        allowed_tools: zod
            .array(zod.string())
            .optional()
            .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
        metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
        files: zod
            .array(
                zod.object({
                    path: zod
                        .string()
                        .max(llmSkillsCreateBodyFilesItemPathMax)
                        .describe(
                            "File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."
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

export const LlmSkillsImportCreateBody = /* @__PURE__ */ zod.object({
    file: zod
        .url()
        .describe(
            'A spec-compliant skill .zip (a SKILL.md plus optional bundled files under scripts\/, references\/, assets\/).'
        ),
})

/**
 * Mint the user's read-only marketplace credential (or rotate it) and return the install command.
 *
 * Per-user: rotating only ever invalidates this user's own credential, never a teammate's.
 */
export const llmSkillsMarketplaceInstallCommandCreateBodyRotateDefault = false

export const LlmSkillsMarketplaceInstallCommandCreateBody = /* @__PURE__ */ zod.object({
    rotate: zod
        .boolean()
        .default(llmSkillsMarketplaceInstallCommandCreateBodyRotateDefault)
        .describe(
            "Roll the existing marketplace credential to issue a fresh token, replacing the old one (this invalidates any setup using the previous token). Ignored when no credential exists yet — the first call always mints one. Only affects this user's own credential."
        ),
})

export const llmSkillsNamePartialUpdateBodyDescriptionMax = 4096

export const llmSkillsNamePartialUpdateBodyLicenseMax = 255

export const llmSkillsNamePartialUpdateBodyCompatibilityMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemPathMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax = 100

export const llmSkillsNamePartialUpdateBodyFileEditsItemPathMax = 500

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
                old: zod.string().describe('Text to find in the target content. Must match exactly once.'),
                new: zod.string().describe('Replacement text.'),
            })
        )
        .optional()
        .describe(
            "List of find\/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body."
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
    allowed_tools: zod
        .array(zod.string())
        .optional()
        .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
    metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
    files: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemPathMax)
                    .describe("File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."),
                content: zod.string().describe('Text content of the file.'),
                content_type: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax)
                    .default(llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault)
                    .describe('MIME type of the file content.'),
            })
        )
        .optional()
        .describe(
            'Bundled files to include with this version. Replaces all files from the previous version. Mutually exclusive with file_edits.'
        ),
    file_edits: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFileEditsItemPathMax)
                    .describe(
                        'Path of the bundled file to edit. Must match an existing file on the current skill version.'
                    ),
                edits: zod
                    .array(
                        zod.object({
                            old: zod.string().describe('Text to find in the target content. Must match exactly once.'),
                            new: zod.string().describe('Replacement text.'),
                        })
                    )
                    .describe("Sequential find\/replace operations to apply to this file's content."),
            })
        )
        .optional()
        .describe(
            "Per-file find\/replace updates. Each entry targets one existing file by path and applies sequential edits to its content. Non-targeted files carry forward unchanged. Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmSkillsNameDuplicateCreateBodyNewNameMax = 64

export const LlmSkillsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmSkillsNameDuplicateCreateBodyNewNameMax)
        .describe('Name for the duplicated skill. Must be unique.'),
})

export const llmSkillsNameFilesCreateBodyPathMax = 500

export const llmSkillsNameFilesCreateBodyContentTypeDefault = `text/plain`
export const llmSkillsNameFilesCreateBodyContentTypeMax = 100

export const LlmSkillsNameFilesCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(llmSkillsNameFilesCreateBodyPathMax)
        .describe("File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."),
    content: zod.string().describe('Text content of the file.'),
    content_type: zod
        .string()
        .max(llmSkillsNameFilesCreateBodyContentTypeMax)
        .default(llmSkillsNameFilesCreateBodyContentTypeDefault)
        .describe('MIME type of the file content.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})

export const llmSkillsNameFilesRenameCreateBodyOldPathMax = 500

export const llmSkillsNameFilesRenameCreateBodyNewPathMax = 500

export const LlmSkillsNameFilesRenameCreateBody = /* @__PURE__ */ zod.object({
    old_path: zod.string().max(llmSkillsNameFilesRenameCreateBodyOldPathMax).describe('Current file path to rename.'),
    new_path: zod
        .string()
        .max(llmSkillsNameFilesRenameCreateBodyNewPathMax)
        .describe('New file path. Must not already exist in the skill.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})
