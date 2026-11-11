// The contract of the CLI library build (`dist/cli-library.mjs`). This file imports nothing, so a
// consumer such as the hog CLI can type-check against it without compiling the MCP sources.

export interface ApiToolSummary {
    name: string
    title: string
    summary: string
    description: string
    /** The catalog category, such as "Feature flags". */
    group: string
    feature: string
    requiredScopes: string[]
    readOnly: boolean
    destructive: boolean
    idempotent: boolean
    openWorld: boolean
    /** The tool sends data to an AI provider, so it runs only where the organization allows that. */
    requiresAiConsent: boolean
}

export interface ApiConnection {
    apiKey: string
    host: string
    projectId?: string
    organizationId?: string
    /** Names the calling CLI in the user agent and in analytics, for example "hog". */
    clientName: string
    clientVersion: string
}

export interface ApiKeyAccess {
    scopes: string[]
    scopedTeams: number[]
    scopedOrganizations: string[]
}

export type ApiToolValidation = { valid: true; input: Record<string, unknown> } | { valid: false; error: string }

/** Why a key lookup or a tool call failed. `code` is stable, so a caller can branch on it. */
export interface ApiToolError {
    code:
        | 'permission_denied'
        | 'validation_error'
        | 'invalid_input'
        | 'needs_confirmation'
        | 'ai_consent_required'
        | 'rate_limited'
        | 'unreachable'
        | 'api_error'
        | 'tool_error'
    message: string
    status?: number
    /** PostHog's own reason for refusing the request. It can repeat request values, so it stays out of
     *  `message` and the caller decides where it is safe to show. */
    detail?: string
    /** The scope PostHog named when it refused the request. */
    missingScope?: string
}

export type ApiToolResult<T> = { ok: true; value: T } | { ok: false; error: ApiToolError }

export interface ApiSearchResult {
    names: string[]
    truncated: boolean
}

export interface ApiToolLibrary {
    tools(): ApiToolSummary[]
    search(query: string): Promise<ApiSearchResult>
    /** A summary of the tool's input schema, or of one field when `fieldPath` names it. */
    schema(tool: string, fieldPath?: string): Promise<unknown>
    validate(tool: string, input: Record<string, unknown>): ApiToolValidation
    missingScopes(granted: string[], required: string[]): string[]
    /** `signal` cancels the lookup, so a caller that stops waiting doesn't keep the process alive. */
    keyAccess(connection: ApiConnection, options?: { signal?: AbortSignal }): Promise<ApiToolResult<ApiKeyAccess>>
    /** Runs the tool and returns its JSON result. */
    call(
        tool: string,
        input: Record<string, unknown>,
        connection: ApiConnection,
        confirm: boolean
    ): Promise<ApiToolResult<unknown>>
    flush(): Promise<void>
}

// The skills library (`dist/cli-skills.mjs`): PostHog's agent skills with the `learn` grammar of the
// MCP server's exec tool, for CLIs that serve them without a login.

export type SkillAssetName = 'product-skills' | 'context-mill'

export interface SkillAssetStatus {
    name: SkillAssetName
    url: string
    /**
     * `network`: this load downloaded the asset, or the server answered 304 for the cached copy.
     * `cache`: the download failed, so the copy in the cache folder served.
     * `unavailable`: the download failed and the cache folder has no usable copy.
     */
    origin: 'network' | 'cache' | 'unavailable'
    /** When the network last returned or confirmed the copy that served, as ISO 8601. Absent when unavailable. */
    fetchedAt?: string
    failure?: string
}

export interface SkillRead {
    source: 'posthog' | 'project'
    skill: string
    /** The file in the skill. A read of the skill itself serves `SKILL.md`. */
    path: string
    readKind: 'skill' | 'file' | 'file_lines'
}

/** One read: a skill's `SKILL.md`, one file in it, or a line range of that file. */
export interface SkillReadRequest {
    /** A skill such as `instrument-integration` or `posthog:instrument-integration`. `catalog` lists every skill. */
    skill: string
    /** A file in the skill, such as `references/COMMANDMENTS.md`. Without it, the read serves `SKILL.md`. */
    file?: string
    /** As `<start>:<end>`. */
    lines?: string
}

/**
 * `learning`: how to use PostHog, such as analyzing a funnel. These come from the product skills.
 * `implementation`: how to add PostHog to code, such as an SDK for one framework. These come from context-mill.
 */
export type SkillKind = 'learning' | 'implementation'

export interface CatalogSkill {
    /** As `read` and `install` take it, such as `tracing-nodejs`. Both also take `posthog:tracing-nodejs`. */
    name: string
    kind: SkillKind
    /** The first line of the skill's description. */
    description: string
}

export interface SkillReadResult {
    text: string
    reads: SkillRead[]
    assets: SkillAssetStatus[]
}

export interface FoundSkill {
    name: string
    description: string
    /** Lines in the skill's files that contain the keywords. */
    matches: { path: string; line: number; text: string }[]
}

export interface SkillSearchResult {
    /** The best matches first. */
    skills: FoundSkill[]
    assets: SkillAssetStatus[]
}

/** The caller's commands, which served text names instead of the MCP `learn` command. */
export interface SkillCommands {
    read(skill: string, file?: string, lines?: string): string
    search(keywords: string): string
    list: string
}

/**
 * The skills that one `catalog` call loaded. `install` writes from them instead of loading them
 * again, so a batch of installs waits for one download, or one failed download.
 */
export interface SkillsRelease {
    readonly assets: SkillAssetStatus[]
}

export interface InstalledSkill {
    id: string
    directory: string
    fileCount: number
}

/** Why a skills call failed. `code` is stable, and `message` already uses the caller's command syntax. */
export interface SkillsError {
    code:
        | 'offline'
        | 'unknown_skill'
        | 'unknown_file'
        | 'unavailable'
        | 'usage'
        | 'already_installed'
        | 'install_failed'
    message: string
    assets?: SkillAssetStatus[]
}

export type SkillsResult<T> = { ok: true; value: T } | { ok: false; error: SkillsError }

export type SkillsFetch = (
    url: string,
    init: { headers: Record<string, string>; signal: AbortSignal }
) => Promise<Response>

export interface SkillsLibraryOptions {
    /**
     * The folder that keeps the last good download of each asset. Every load downloads first, and
     * reads this folder only when the download fails, or to answer a 304. Without it, nothing is cached.
     */
    cacheDir?: string
    /** The commands that served text names. Defaults to the MCP `learn` command. */
    commands?: SkillCommands
    fetch?: SkillsFetch
    responseTimeoutMs?: number
    downloadTimeoutMs?: number
    now?: () => number
}

export interface SkillsLibrary {
    read(request: SkillReadRequest): Promise<SkillsResult<SkillReadResult>>
    /** Finds skills whose name, description or files contain the keywords. */
    search(keywords: string): Promise<SkillsResult<SkillSearchResult>>
    /** The `posthog:instrument-*` skills. Downloads only context-mill, not the product skills. */
    instrumentSkills(): Promise<SkillsResult<{ skills: string[]; assets: SkillAssetStatus[] }>>
    /** Every skill `read` serves. Each one can be installed. */
    catalog(): Promise<SkillsResult<{ skills: CatalogSkill[]; assets: SkillAssetStatus[]; release: SkillsRelease }>>
    /**
     * Writes a skill from `catalog` into `<skillsDir>/<id>` under `cwd`, where `id` is the name without its
     * `posthog:` prefix. `name` may leave the prefix out. `skillsDir` defaults to `.agents/skills`. A write
     * that would land outside `cwd`, through `..` or a symlink, fails with `install_failed`. Without
     * `release`, the call loads the skills itself.
     */
    install(
        name: string,
        options: { cwd: string; force?: boolean; skillsDir?: string; release?: SkillsRelease }
    ): Promise<SkillsResult<{ skill: InstalledSkill; assets: SkillAssetStatus[] }>>
}
