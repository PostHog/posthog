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

export const communitySkillsInstallCreateBodyNewNameMax = 64

export const CommunitySkillsInstallCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(communitySkillsInstallCreateBodyNewNameMax)
        .optional()
        .describe("Name for the installed skill in your team. Defaults to the community skill's slug."),
    variables: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            "Values for a template skill's declared variables, as a {name: value} map. Required only when installing a template (see the skill's `template_variables`); ignored for non-template skills."
        ),
})

/**
 * Bind a catalog entry's template variables and return the text a create form starts from.
 *
 * Persists nothing, so it needs no more access than reading the catalog already does — the
 * result is prefill, and the caller creates the skill or scout through its own product's path.
 */
export const CommunitySkillsRenderCreateBody = /* @__PURE__ */ zod.object({
    variables: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            "Values for a template skill's declared variables, as a {name: value} map. Required only when rendering a template (see the skill's `template_variables`); ignored for non-template skills."
        ),
})

export const llmSkillsCreateBodyNameMax = 64

export const llmSkillsCreateBodyDescriptionMax = 1024

export const llmSkillsCreateBodyLicenseMax = 255

export const llmSkillsCreateBodyCompatibilityMax = 500

export const llmSkillsCreateBodyOwnersMax = 25

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
            .describe('What this skill does and when to use it. Max 1024 characters.'),
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
        owners: zod
            .array(zod.uuid())
            .max(llmSkillsCreateBodyOwnersMax)
            .optional()
            .describe(
                "User UUIDs to set as the skill's owners. Each must be a member of this project. Defaults to the creating user when omitted; pass an empty list to create with no owners."
            ),
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
    .describe('Create serializer — accepts bundled files and owners as write-only input on POST.')

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

export const llmSkillsNamePartialUpdateBodyDescriptionMax = 1024

export const llmSkillsNamePartialUpdateBodyLicenseMax = 255

export const llmSkillsNamePartialUpdateBodyCompatibilityMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemPathMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax = 100

export const llmSkillsNamePartialUpdateBodyFileEditsItemPathMax = 500

export const llmSkillsNamePartialUpdateBodyOwnersMax = 25

export const llmSkillsNamePartialUpdateBodyVersionDescriptionMax = 400

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
    owners: zod
        .array(zod.uuid())
        .max(llmSkillsNamePartialUpdateBodyOwnersMax)
        .optional()
        .describe(
            "Replace the skill's owners with these user UUIDs (each a member of this project). Omit to leave owners unchanged; pass an empty list to clear them. Owners are keyed on the logical skill, so setting them is independent of the version being published — a body edit alone never changes ownership."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. Used for optimistic concurrency checks. Required when publishing content changes; optional for an owner-only update (when omitted, owners are replaced without a concurrency check).'
        ),
    version_description: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyVersionDescriptionMax)
        .optional()
        .describe('Optional note describing what changed in this version. Shown in the version history.'),
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

export const llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunIntervalMinutesMin = 30
export const llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunIntervalMinutesMax = 43200

export const llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunCronScheduleMax = 100

export const llmSkillsNamePublishCommunityCreateBodyScoutConfigOneTagsItemMax = 50

export const llmSkillsNamePublishCommunityCreateBodyScoutConfigOneTagsMax = 10

export const llmSkillsNamePublishCommunityCreateBodyDisplayNameOneMax = 64

export const llmSkillsNamePublishCommunityCreateBodyDisplayNameOneRegExp = new RegExp('^[^\\u0000-\\u001f\\u007f]\*$')
export const llmSkillsNamePublishCommunityCreateBodyDisplayNameTwoMax = 0

export const llmSkillsNamePublishCommunityCreateBodyTagsItemMax = 64

export const llmSkillsNamePublishCommunityCreateBodyAuthorHandleOneMax = 39

export const llmSkillsNamePublishCommunityCreateBodyAuthorHandleOneRegExp = new RegExp(
    '^$|^[a-zA-Z0-9](?:-?[a-zA-Z0-9]){0,38}$'
)
export const llmSkillsNamePublishCommunityCreateBodyAuthorHandleTwoMax = 0

export const LlmSkillsNamePublishCommunityCreateBody = /* @__PURE__ */ zod.object({
    scout_config: zod
        .object({
            run_interval_minutes: zod
                .number()
                .min(llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunIntervalMinutesMin)
                .max(llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunIntervalMinutesMax)
                .optional()
                .describe('How often the scout runs, in minutes. Ignored when run_cron_schedule is set.'),
            run_cron_schedule: zod
                .string()
                .max(llmSkillsNamePublishCommunityCreateBodyScoutConfigOneRunCronScheduleMax)
                .optional()
                .describe(
                    "Five-field cron expression for the scout's schedule, which takes precedence over the interval."
                ),
            emit: zod
                .boolean()
                .optional()
                .describe('Whether the scout writes its reports to the inbox. False means it runs as a dry run.'),
            tags: zod
                .array(zod.string().max(llmSkillsNamePublishCommunityCreateBodyScoutConfigOneTagsItemMax))
                .max(llmSkillsNamePublishCommunityCreateBodyScoutConfigOneTagsMax)
                .optional()
                .describe('Tags used to group the scout in the fleet.'),
        })
        .describe(
            "The scout settings a published scout travels with. Every field is optional. An omitted field\nmeans the scout-create form's own default applies."
        )
        .optional()
        .describe(
            'Schedule, emit posture and tags to publish alongside a scout, so it arrives in another project with its cadence intact. Rejected for a skill that is not a scout.'
        ),
    display_name: zod
        .union([
            zod
                .string()
                .max(llmSkillsNamePublishCommunityCreateBodyDisplayNameOneMax)
                .regex(llmSkillsNamePublishCommunityCreateBodyDisplayNameOneRegExp),
            zod.string().max(llmSkillsNamePublishCommunityCreateBodyDisplayNameTwoMax),
        ])
        .optional()
        .describe(
            'Human-friendly display name for the community listing. Defaults to a title-cased skill slug. Must be a single line: it is used as the pull request title and commit message.'
        ),
    tags: zod
        .array(zod.string().max(llmSkillsNamePublishCommunityCreateBodyTagsItemMax))
        .optional()
        .describe("Tags used for filtering and discovery in the marketplace, e.g. ['web-analytics', 'triage']."),
    author_handle: zod
        .union([
            zod
                .string()
                .max(llmSkillsNamePublishCommunityCreateBodyAuthorHandleOneMax)
                .regex(llmSkillsNamePublishCommunityCreateBodyAuthorHandleOneRegExp),
            zod.string().max(llmSkillsNamePublishCommunityCreateBodyAuthorHandleTwoMax),
        ])
        .optional()
        .describe(
            "The publisher's GitHub username, used for public attribution on the listing and PR. Optional, and self-reported: it is not verified against the publisher's PostHog account."
        ),
})
