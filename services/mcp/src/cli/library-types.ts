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
    readKind: 'skill' | 'file' | 'file_search' | 'file_lines'
}

/**
 * A `learn` command, in the parts `hog learn` takes it as. Give at most one of `search` (keywords),
 * `describe` and `lines`. Without any of them, `skill` and `paths` read files, and nothing is the overview.
 */
export interface LearnRequest {
    /** A skill such as `posthog:instrument-integration`, or `skills` to list every skill. */
    skill?: string
    /** Files in `skill`, such as `references/COMMANDMENTS.md`. With `describe`, more skills to describe. */
    paths: readonly string[]
    search?: string
    describe?: boolean
    /** As `<start>:<end>`. */
    lines?: string
}

export type LearnOutput =
    | { kind: 'overview'; commands: string[] }
    | { kind: 'list'; skills: string[]; count: number; truncated: boolean }
    | { kind: 'text'; text: string }

export interface LearnResult {
    output: LearnOutput
    reads: SkillRead[]
    assets: SkillAssetStatus[]
}

export interface InstallableSkill {
    id: string
    name: string
    description: string
    tags: string[]
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
        | 'unknown_topic'
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
    /** The command that served text names, such as `hog learn`. Defaults to `learn`. */
    learnCommand?: string
    fetch?: SkillsFetch
    responseTimeoutMs?: number
    downloadTimeoutMs?: number
    now?: () => number
}

export interface SkillsLibrary {
    learn(request: LearnRequest): Promise<SkillsResult<LearnResult>>
    /** The `posthog:instrument-*` skills. Downloads only context-mill, not the product skills. */
    instrumentSkills(): Promise<SkillsResult<{ skills: string[]; assets: SkillAssetStatus[] }>>
    installable(): Promise<SkillsResult<{ skills: InstallableSkill[]; assets: SkillAssetStatus[] }>>
    /** Writes a skill into `.agents/skills/<id>` under `cwd`, as `posthog-cli api skill install` does. */
    install(
        id: string,
        options: { cwd: string; force?: boolean }
    ): Promise<SkillsResult<{ skill: InstalledSkill; assets: SkillAssetStatus[] }>>
}
