/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const lLMSkillOutlineEntryApiLevelMax = 6

export const LLMSkillOutlineEntryApi = zod.object({
    level: zod.number().min(1).max(lLMSkillOutlineEntryApiLevelMax).describe('Markdown heading level (1-6).'),
    text: zod.string().describe('Heading text.'),
})

export type LLMSkillOutlineEntryApi = zod.input<typeof LLMSkillOutlineEntryApi>
export type LLMSkillOutlineEntryApiOutput = zod.output<typeof LLMSkillOutlineEntryApi>

export const lLMSkillListApiNameMax = 64

export const lLMSkillListApiDescriptionMax = 4096

export const lLMSkillListApiLicenseMax = 255

export const lLMSkillListApiCompatibilityMax = 500

export const LLMSkillListApi = zod
    .object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(lLMSkillListApiNameMax)
            .describe('Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.'),
        description: zod
            .string()
            .max(lLMSkillListApiDescriptionMax)
            .describe('What this skill does and when to use it. Max 4096 characters.'),
        license: zod
            .string()
            .max(lLMSkillListApiLicenseMax)
            .optional()
            .describe('License name or reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(lLMSkillListApiCompatibilityMax)
            .optional()
            .describe('Environment requirements (intended product, system packages, network access, etc.).'),
        allowed_tools: zod
            .array(zod.string())
            .optional()
            .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
        metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
        category: zod
            .string()
            .describe(
                'Server-owned classification — set by the producing system (the Signals harness stamps \"scout\"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name.'
            ),
        owners: zod
            .array(UserBasicApi)
            .describe(
                "Users who own this skill, seed-creator first. Ownership is keyed on the logical skill (not a version), so it's stable across edits. Prefer this over created_by to learn who to route reviews or questions to. Set via the owners field on create\/update (a list of user UUIDs). Empty for scout sandbox fetches of skills that haven't opted into the report channel."
            ),
        outline: zod
            .array(LLMSkillOutlineEntryApi)
            .describe(
                'Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents.'
            ),
        version: zod.number(),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        deleted: zod.boolean(),
        is_latest: zod.boolean(),
        latest_version: zod.number(),
        version_count: zod.number(),
        first_version_created_at: zod.string(),
    })
    .describe('List serializer that omits body and file manifest — progressive disclosure (Level 1).')

export type LLMSkillListApi = zod.input<typeof LLMSkillListApi>
export type LLMSkillListApiOutput = zod.output<typeof LLMSkillListApi>

export const PaginatedLLMSkillListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LLMSkillListApi),
})

export type PaginatedLLMSkillListListApi = zod.input<typeof PaginatedLLMSkillListListApi>
export type PaginatedLLMSkillListListApiOutput = zod.output<typeof PaginatedLLMSkillListListApi>

export const lLMSkillFileInputApiPathMax = 500

export const lLMSkillFileInputApiContentTypeDefault = `text/plain`
export const lLMSkillFileInputApiContentTypeMax = 100

export const LLMSkillFileInputApi = zod.object({
    path: zod
        .string()
        .max(lLMSkillFileInputApiPathMax)
        .describe("File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."),
    content: zod.string().describe('Text content of the file.'),
    content_type: zod
        .string()
        .max(lLMSkillFileInputApiContentTypeMax)
        .default(lLMSkillFileInputApiContentTypeDefault)
        .describe('MIME type of the file content.'),
})

export type LLMSkillFileInputApi = zod.input<typeof LLMSkillFileInputApi>
export type LLMSkillFileInputApiOutput = zod.output<typeof LLMSkillFileInputApi>

export const lLMSkillCreateApiNameMax = 64

export const lLMSkillCreateApiDescriptionMax = 4096

export const lLMSkillCreateApiLicenseMax = 255

export const lLMSkillCreateApiCompatibilityMax = 500

export const lLMSkillCreateApiOwnersMax = 25

export const LLMSkillCreateApi = zod
    .object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(lLMSkillCreateApiNameMax)
            .describe('Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.'),
        description: zod
            .string()
            .max(lLMSkillCreateApiDescriptionMax)
            .describe('What this skill does and when to use it. Max 4096 characters.'),
        body_total_length: zod
            .number()
            .describe(
                'Total length of the full body in characters, independent of any body_offset\/body_length paging. Compare against the length of the returned body to detect a truncated response.'
            ),
        body_next_offset: zod
            .number()
            .nullable()
            .describe(
                'When body_length paging stops before the end of the body, the character offset to request next (pass as body_offset). Null when the returned body reaches the end.'
            ),
        body: zod.string().describe('The SKILL.md instruction content (markdown).'),
        license: zod
            .string()
            .max(lLMSkillCreateApiLicenseMax)
            .optional()
            .describe('License name or reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(lLMSkillCreateApiCompatibilityMax)
            .optional()
            .describe('Environment requirements (intended product, system packages, network access, etc.).'),
        allowed_tools: zod
            .array(zod.string())
            .optional()
            .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
        metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
        category: zod
            .string()
            .describe(
                'Server-owned classification — set by the producing system (the Signals harness stamps \"scout\"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name.'
            ),
        owners: zod
            .array(zod.uuid())
            .max(lLMSkillCreateApiOwnersMax)
            .optional()
            .describe(
                "User UUIDs to set as the skill's owners. Each must be a member of this project. Defaults to the creating user when omitted; pass an empty list to create with no owners."
            ),
        files: zod
            .array(LLMSkillFileInputApi)
            .optional()
            .describe('Bundled files to include with the initial version (scripts, references, assets).'),
        outline: zod
            .array(LLMSkillOutlineEntryApi)
            .describe(
                'Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents.'
            ),
        version: zod.number(),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        deleted: zod.boolean(),
        is_latest: zod.boolean(),
        latest_version: zod.number(),
        version_count: zod.number(),
        first_version_created_at: zod.string(),
    })
    .describe('Create serializer — accepts bundled files and owners as write-only input on POST.')

export type LLMSkillCreateApi = zod.input<typeof LLMSkillCreateApi>
export type LLMSkillCreateApiOutput = zod.output<typeof LLMSkillCreateApi>

export const lLMSkillFileManifestApiPathMax = 500

export const lLMSkillFileManifestApiContentTypeMax = 100

export const LLMSkillFileManifestApi = zod.object({
    path: zod.string().max(lLMSkillFileManifestApiPathMax),
    content_type: zod.string().max(lLMSkillFileManifestApiContentTypeMax).optional(),
})

export type LLMSkillFileManifestApi = zod.input<typeof LLMSkillFileManifestApi>
export type LLMSkillFileManifestApiOutput = zod.output<typeof LLMSkillFileManifestApi>

export const lLMSkillApiNameMax = 64

export const lLMSkillApiDescriptionMax = 4096

export const lLMSkillApiLicenseMax = 255

export const lLMSkillApiCompatibilityMax = 500

export const LLMSkillApi = zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(lLMSkillApiNameMax)
        .describe('Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.'),
    description: zod
        .string()
        .max(lLMSkillApiDescriptionMax)
        .describe('What this skill does and when to use it. Max 4096 characters.'),
    body_total_length: zod
        .number()
        .describe(
            'Total length of the full body in characters, independent of any body_offset\/body_length paging. Compare against the length of the returned body to detect a truncated response.'
        ),
    body_next_offset: zod
        .number()
        .nullable()
        .describe(
            'When body_length paging stops before the end of the body, the character offset to request next (pass as body_offset). Null when the returned body reaches the end.'
        ),
    body: zod.string().describe('The SKILL.md instruction content (markdown).'),
    license: zod
        .string()
        .max(lLMSkillApiLicenseMax)
        .optional()
        .describe('License name or reference to a bundled license file.'),
    compatibility: zod
        .string()
        .max(lLMSkillApiCompatibilityMax)
        .optional()
        .describe('Environment requirements (intended product, system packages, network access, etc.).'),
    allowed_tools: zod
        .array(zod.string())
        .optional()
        .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
    metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
    category: zod
        .string()
        .describe(
            'Server-owned classification — set by the producing system (the Signals harness stamps \"scout\"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name.'
        ),
    owners: zod
        .array(UserBasicApi)
        .describe(
            "Users who own this skill, seed-creator first. Ownership is keyed on the logical skill (not a version), so it's stable across edits. Prefer this over created_by to learn who to route reviews or questions to. Set via the owners field on create\/update (a list of user UUIDs). Empty for scout sandbox fetches of skills that haven't opted into the report channel."
        ),
    files: zod
        .array(LLMSkillFileManifestApi)
        .describe(
            'Bundled files manifest. Each entry is path + content_type only; fetch content via \/llm_skills\/name\/{name}\/files\/{path}\/.'
        ),
    outline: zod
        .array(LLMSkillOutlineEntryApi)
        .describe(
            'Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents.'
        ),
    version: zod.number(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string(),
})

export type LLMSkillApi = zod.input<typeof LLMSkillApi>
export type LLMSkillApiOutput = zod.output<typeof LLMSkillApi>

export const LLMSkillImportApi = zod.object({
    file: zod
        .url()
        .describe(
            'A spec-compliant skill .zip (a SKILL.md plus optional bundled files under scripts\/, references\/, assets\/).'
        ),
})

export type LLMSkillImportApi = zod.input<typeof LLMSkillImportApi>
export type LLMSkillImportApiOutput = zod.output<typeof LLMSkillImportApi>

export const LLMSkillMarketplaceCommandStatusEnumApi = zod
    .enum(['absent', 'exists', 'created', 'rotated'])
    .describe('\* `absent` - absent\n\* `exists` - exists\n\* `created` - created\n\* `rotated` - rotated')

export type LLMSkillMarketplaceCommandStatusEnumApi = zod.input<typeof LLMSkillMarketplaceCommandStatusEnumApi>
export type LLMSkillMarketplaceCommandStatusEnumApiOutput = zod.output<typeof LLMSkillMarketplaceCommandStatusEnumApi>

export const LLMSkillMarketplaceCommandApi = zod.object({
    status: LLMSkillMarketplaceCommandStatusEnumApi.describe(
        'absent: no credential yet. exists: one already exists (no token returned). created: a new credential was just minted. rotated: the existing credential was rolled.\n\n\* `absent` - absent\n\* `exists` - exists\n\* `created` - created\n\* `rotated` - rotated'
    ),
    connected: zod
        .boolean()
        .describe("Whether this user already has a marketplace credential for the team's skill store."),
    plugin_name: zod.string().describe('The plugin name the command installs (Claude Code and Codex).'),
    marketplace_name: zod.string().describe('The marketplace name, used by the Codex install command.'),
    label: zod.string().describe("Label of this user's marketplace credential (a scoped Personal API Key)."),
    repo_url: zod.string().describe('The marketplace git repository URL, with no credential embedded.'),
    command: zod
        .string()
        .nullable()
        .describe(
            'Claude Code: ready-to-paste `\/plugin marketplace add` command with the live token embedded. Returned only when a token was just issued (status created\/rotated); null otherwise.'
        ),
    command_template: zod
        .string()
        .describe(
            'Claude Code install command with a YOUR_PHS_TOKEN placeholder instead of a live token; always present.'
        ),
    codex_command: zod
        .string()
        .nullable()
        .describe(
            'OpenAI Codex: two-line `codex plugin marketplace add` + `codex plugin add` command with the live token embedded. Returned only when a token was just issued (status created\/rotated); null otherwise.'
        ),
    codex_command_template: zod
        .string()
        .describe('Codex install command with a YOUR_PHS_TOKEN placeholder instead of a live token; always present.'),
    token: zod
        .string()
        .nullable()
        .describe(
            'The raw read-only `phx_` credential. Returned once, only when minted or rotated; it cannot be retrieved again afterwards.'
        ),
    mask_value: zod.string().nullable().describe('Masked preview of the existing credential (e.g. phx_...abcd).'),
    created_at: zod.iso.datetime({ offset: true }).nullable().describe('When the credential was created.'),
    last_rolled_at: zod.iso.datetime({ offset: true }).nullable().describe('When the credential was last rotated.'),
})

export type LLMSkillMarketplaceCommandApi = zod.input<typeof LLMSkillMarketplaceCommandApi>
export type LLMSkillMarketplaceCommandApiOutput = zod.output<typeof LLMSkillMarketplaceCommandApi>

export const lLMSkillMarketplaceIssueApiRotateDefault = false

export const LLMSkillMarketplaceIssueApi = zod.object({
    rotate: zod
        .boolean()
        .default(lLMSkillMarketplaceIssueApiRotateDefault)
        .describe(
            "Roll the existing marketplace credential to issue a fresh token, replacing the old one (this invalidates any setup using the previous token). Ignored when no credential exists yet — the first call always mints one. Only affects this user's own credential."
        ),
})

export type LLMSkillMarketplaceIssueApi = zod.input<typeof LLMSkillMarketplaceIssueApi>
export type LLMSkillMarketplaceIssueApiOutput = zod.output<typeof LLMSkillMarketplaceIssueApi>

export const LLMSkillEditOperationApi = zod.object({
    old: zod.string().describe('Text to find in the target content. Must match exactly once.'),
    new: zod.string().describe('Replacement text.'),
})

export type LLMSkillEditOperationApi = zod.input<typeof LLMSkillEditOperationApi>
export type LLMSkillEditOperationApiOutput = zod.output<typeof LLMSkillEditOperationApi>

export const lLMSkillFileEditApiPathMax = 500

export const LLMSkillFileEditApi = zod.object({
    path: zod
        .string()
        .max(lLMSkillFileEditApiPathMax)
        .describe('Path of the bundled file to edit. Must match an existing file on the current skill version.'),
    edits: zod
        .array(LLMSkillEditOperationApi)
        .describe("Sequential find\/replace operations to apply to this file's content."),
})

export type LLMSkillFileEditApi = zod.input<typeof LLMSkillFileEditApi>
export type LLMSkillFileEditApiOutput = zod.output<typeof LLMSkillFileEditApi>

export const patchedLLMSkillPublishApiDescriptionMax = 4096

export const patchedLLMSkillPublishApiLicenseMax = 255

export const patchedLLMSkillPublishApiCompatibilityMax = 500

export const patchedLLMSkillPublishApiOwnersMax = 25

export const PatchedLLMSkillPublishApi = zod.object({
    body: zod
        .string()
        .optional()
        .describe(
            'Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits.'
        ),
    edits: zod
        .array(LLMSkillEditOperationApi)
        .optional()
        .describe(
            "List of find\/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body."
        ),
    description: zod
        .string()
        .max(patchedLLMSkillPublishApiDescriptionMax)
        .optional()
        .describe('Updated description for the new version.'),
    license: zod.string().max(patchedLLMSkillPublishApiLicenseMax).optional().describe('License name or reference.'),
    compatibility: zod
        .string()
        .max(patchedLLMSkillPublishApiCompatibilityMax)
        .optional()
        .describe('Environment requirements.'),
    allowed_tools: zod
        .array(zod.string())
        .optional()
        .describe('List of pre-approved tools the skill may use. Tool names cannot contain whitespace.'),
    metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
    files: zod
        .array(LLMSkillFileInputApi)
        .optional()
        .describe(
            'Bundled files to include with this version. Replaces all files from the previous version. Mutually exclusive with file_edits.'
        ),
    file_edits: zod
        .array(LLMSkillFileEditApi)
        .optional()
        .describe(
            "Per-file find\/replace updates. Each entry targets one existing file by path and applies sequential edits to its content. Non-targeted files carry forward unchanged. Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files."
        ),
    owners: zod
        .array(zod.uuid())
        .max(patchedLLMSkillPublishApiOwnersMax)
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
})

export type PatchedLLMSkillPublishApi = zod.input<typeof PatchedLLMSkillPublishApi>
export type PatchedLLMSkillPublishApiOutput = zod.output<typeof PatchedLLMSkillPublishApi>

export const lLMSkillDuplicateApiNewNameMax = 64

export const LLMSkillDuplicateApi = zod.object({
    new_name: zod
        .string()
        .max(lLMSkillDuplicateApiNewNameMax)
        .describe('Name for the duplicated skill. Must be unique.'),
})

export type LLMSkillDuplicateApi = zod.input<typeof LLMSkillDuplicateApi>
export type LLMSkillDuplicateApiOutput = zod.output<typeof LLMSkillDuplicateApi>

export const lLMSkillFileCreateApiPathMax = 500

export const lLMSkillFileCreateApiContentTypeDefault = `text/plain`
export const lLMSkillFileCreateApiContentTypeMax = 100

export const LLMSkillFileCreateApi = zod.object({
    path: zod
        .string()
        .max(lLMSkillFileCreateApiPathMax)
        .describe("File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."),
    content: zod.string().describe('Text content of the file.'),
    content_type: zod
        .string()
        .max(lLMSkillFileCreateApiContentTypeMax)
        .default(lLMSkillFileCreateApiContentTypeDefault)
        .describe('MIME type of the file content.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})

export type LLMSkillFileCreateApi = zod.input<typeof LLMSkillFileCreateApi>
export type LLMSkillFileCreateApiOutput = zod.output<typeof LLMSkillFileCreateApi>

export const lLMSkillFileRenameApiOldPathMax = 500

export const lLMSkillFileRenameApiNewPathMax = 500

export const LLMSkillFileRenameApi = zod.object({
    old_path: zod.string().max(lLMSkillFileRenameApiOldPathMax).describe('Current file path to rename.'),
    new_path: zod
        .string()
        .max(lLMSkillFileRenameApiNewPathMax)
        .describe('New file path. Must not already exist in the skill.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})

export type LLMSkillFileRenameApi = zod.input<typeof LLMSkillFileRenameApi>
export type LLMSkillFileRenameApiOutput = zod.output<typeof LLMSkillFileRenameApi>

export const lLMSkillFileApiPathMax = 500

export const lLMSkillFileApiContentTypeMax = 100

export const LLMSkillFileApi = zod.object({
    path: zod.string().max(lLMSkillFileApiPathMax),
    content: zod.string(),
    content_type: zod.string().max(lLMSkillFileApiContentTypeMax).optional(),
})

export type LLMSkillFileApi = zod.input<typeof LLMSkillFileApi>
export type LLMSkillFileApiOutput = zod.output<typeof LLMSkillFileApi>

export const LLMSkillVersionSummaryApi = zod.object({
    id: zod.uuid(),
    version: zod.number(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    is_latest: zod.boolean(),
})

export type LLMSkillVersionSummaryApi = zod.input<typeof LLMSkillVersionSummaryApi>
export type LLMSkillVersionSummaryApiOutput = zod.output<typeof LLMSkillVersionSummaryApi>

export const LLMSkillResolveResponseApi = zod.object({
    skill: LLMSkillApi,
    versions: zod.array(LLMSkillVersionSummaryApi),
    has_more: zod.boolean(),
})

export type LLMSkillResolveResponseApi = zod.input<typeof LLMSkillResolveResponseApi>
export type LLMSkillResolveResponseApiOutput = zod.output<typeof LLMSkillResolveResponseApi>
