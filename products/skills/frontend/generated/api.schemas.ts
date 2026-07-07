/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LLMSkillOutlineEntryApi {
    /**
     * Markdown heading level (1-6).
     * @minimum 1
     * @maximum 6
     */
    level: number
    /** Heading text. */
    text: string
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillListApiMetadata = { [key: string]: unknown }

/**
 * List serializer that omits body and file manifest — progressive disclosure (Level 1).
 */
export interface LLMSkillListApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. Tool names cannot contain whitespace. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillListApiMetadata
    /** Server-owned classification — set by the producing system (the Signals harness stamps "scout"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name. */
    readonly category: string
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
}

export interface PaginatedLLMSkillListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMSkillListApi[]
}

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillCreateApiMetadata = { [key: string]: unknown }

export interface LLMSkillFileInputApi {
    /**
     * File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'.
     * @maxLength 500
     */
    path: string
    /** Text content of the file. */
    content: string
    /**
     * MIME type of the file content.
     * @maxLength 100
     */
    content_type?: string
}

/**
 * Create serializer — accepts bundled files as write-only input on POST.
 */
export interface LLMSkillCreateApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /** The SKILL.md instruction content (markdown). */
    body: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. Tool names cannot contain whitespace. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillCreateApiMetadata
    /** Server-owned classification — set by the producing system (the Signals harness stamps "scout"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name. */
    readonly category: string
    /** Bundled files to include with the initial version (scripts, references, assets). */
    files?: LLMSkillFileInputApi[]
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
}

export interface LLMSkillImportApi {
    /** A spec-compliant skill .zip (a SKILL.md plus optional bundled files under scripts/, references/, assets/). */
    file: string
}

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillApiMetadata = { [key: string]: unknown }

export interface LLMSkillFileManifestApi {
    /** @maxLength 500 */
    path: string
    /** @maxLength 100 */
    content_type?: string
}

export interface LLMSkillApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /** The SKILL.md instruction content (markdown). */
    body: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. Tool names cannot contain whitespace. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillApiMetadata
    /** Server-owned classification — set by the producing system (the Signals harness stamps "scout"), not writable via the API. Empty for an ordinary skill. Groups skills into their own surface (e.g. the Scouts tab) independently of the skill name. */
    readonly category: string
    /** Bundled files manifest. Each entry is path + content_type only; fetch content via /llm_skills/name/{name}/files/{path}/. */
    readonly files: readonly LLMSkillFileManifestApi[]
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
}

/**
 * * `absent` - absent
 * * `exists` - exists
 * * `created` - created
 * * `rotated` - rotated
 */
export type LLMSkillMarketplaceCommandStatusEnumApi =
    (typeof LLMSkillMarketplaceCommandStatusEnumApi)[keyof typeof LLMSkillMarketplaceCommandStatusEnumApi]

export const LLMSkillMarketplaceCommandStatusEnumApi = {
    Absent: 'absent',
    Exists: 'exists',
    Created: 'created',
    Rotated: 'rotated',
} as const

export interface LLMSkillMarketplaceCommandApi {
    /** absent: no credential yet. exists: one already exists (no token returned). created: a new credential was just minted. rotated: the existing credential was rolled.
     *
     * * `absent` - absent
     * * `exists` - exists
     * * `created` - created
     * * `rotated` - rotated */
    status: LLMSkillMarketplaceCommandStatusEnumApi
    /** Whether this user already has a marketplace credential for the team's skill store. */
    connected: boolean
    /** The plugin name the command installs (Claude Code and Codex). */
    plugin_name: string
    /** The marketplace name, used by the Codex install command. */
    marketplace_name: string
    /** Label of this user's marketplace credential (a scoped Personal API Key). */
    label: string
    /** The marketplace git repository URL, with no credential embedded. */
    repo_url: string
    /**
     * Claude Code: ready-to-paste `/plugin marketplace add` command with the live token embedded. Returned only when a token was just issued (status created/rotated); null otherwise.
     * @nullable
     */
    command: string | null
    /** Claude Code install command with a YOUR_PHS_TOKEN placeholder instead of a live token; always present. */
    command_template: string
    /**
     * OpenAI Codex: two-line `codex plugin marketplace add` + `codex plugin add` command with the live token embedded. Returned only when a token was just issued (status created/rotated); null otherwise.
     * @nullable
     */
    codex_command: string | null
    /** Codex install command with a YOUR_PHS_TOKEN placeholder instead of a live token; always present. */
    codex_command_template: string
    /**
     * The raw read-only `phx_` credential. Returned once, only when minted or rotated; it cannot be retrieved again afterwards.
     * @nullable
     */
    token: string | null
    /**
     * Masked preview of the existing credential (e.g. phx_...abcd).
     * @nullable
     */
    mask_value: string | null
    /**
     * When the credential was created.
     * @nullable
     */
    created_at: string | null
    /**
     * When the credential was last rotated.
     * @nullable
     */
    last_rolled_at: string | null
}

export interface LLMSkillMarketplaceIssueApi {
    /** Roll the existing marketplace credential to issue a fresh token, replacing the old one (this invalidates any setup using the previous token). Ignored when no credential exists yet — the first call always mints one. Only affects this user's own credential. */
    rotate?: boolean
}

/**
 * Arbitrary key-value metadata.
 */
export type PatchedLLMSkillPublishApiMetadata = { [key: string]: unknown }

export interface LLMSkillEditOperationApi {
    /** Text to find in the target content. Must match exactly once. */
    old: string
    /** Replacement text. */
    new: string
}

export interface LLMSkillFileEditApi {
    /**
     * Path of the bundled file to edit. Must match an existing file on the current skill version.
     * @maxLength 500
     */
    path: string
    /** Sequential find/replace operations to apply to this file's content. */
    edits: LLMSkillEditOperationApi[]
}

export interface PatchedLLMSkillPublishApi {
    /** Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits. */
    body?: string
    /** List of find/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body. */
    edits?: LLMSkillEditOperationApi[]
    /**
     * Updated description for the new version.
     * @maxLength 4096
     */
    description?: string
    /**
     * License name or reference.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements.
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. Tool names cannot contain whitespace. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: PatchedLLMSkillPublishApiMetadata
    /** Bundled files to include with this version. Replaces all files from the previous version. Mutually exclusive with file_edits. */
    files?: LLMSkillFileInputApi[]
    /** Per-file find/replace updates. Each entry targets one existing file by path and applies sequential edits to its content. Non-targeted files carry forward unchanged. Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files. */
    file_edits?: LLMSkillFileEditApi[]
    /**
     * Latest version you are editing from. Used for optimistic concurrency checks.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillDuplicateApi {
    /**
     * Name for the duplicated skill. Must be unique.
     * @maxLength 64
     */
    new_name: string
}

export interface LLMSkillFileCreateApi {
    /**
     * File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'.
     * @maxLength 500
     */
    path: string
    /** Text content of the file. */
    content: string
    /**
     * MIME type of the file content.
     * @maxLength 100
     */
    content_type?: string
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillFileRenameApi {
    /**
     * Current file path to rename.
     * @maxLength 500
     */
    old_path: string
    /**
     * New file path. Must not already exist in the skill.
     * @maxLength 500
     */
    new_path: string
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillFileApi {
    /** @maxLength 500 */
    path: string
    content: string
    /** @maxLength 100 */
    content_type?: string
}

export interface LLMSkillVersionSummaryApi {
    readonly id: string
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly is_latest: boolean
}

export interface LLMSkillResolveResponseApi {
    skill: LLMSkillApi
    versions: LLMSkillVersionSummaryApi[]
    has_more: boolean
}

export type LlmSkillsListParams = {
    /**
     * Filter skills to this exact category. Pass "scout" for Signals scouts, or an empty string to return only uncategorized skills. Omit the parameter entirely to return skills of every category.
     */
    category?: string
    /**
     * Filter skills by the ID of the user who created them.
     */
    created_by_id?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional substring filter applied to skill names and descriptions.
     */
    search?: string
}

export type LlmSkillsNameRetrieveParams = {
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmSkillsNameExportRetrieveParams = {
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmSkillsNameFilesRetrieveParams = {
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmSkillsNameFilesDestroyParams = {
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export type LlmSkillsResolveNameRetrieveParams = {
    /**
     * Return versions older than this version number. Mutually exclusive with offset.
     * @minimum 1
     */
    before_version?: number
    /**
     * Maximum number of versions to return per page (1-100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Zero-based offset into version history for pagination. Mutually exclusive with before_version.
     * @minimum 0
     */
    offset?: number
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
    /**
     * Exact skill version UUID to resolve.
     */
    version_id?: string
}
