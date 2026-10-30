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
