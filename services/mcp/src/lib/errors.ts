import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

import { getPostHogClient } from '@/lib/analytics'
import { sanitizeHeaderValue } from '@/lib/utils'

export enum ErrorCode {
    INVALID_API_KEY = 'INVALID_API_KEY',
    INACTIVE_OAUTH_TOKEN = 'INACTIVE_OAUTH_TOKEN',
}

export class MCPToolError extends Error {
    public readonly tool: string
    public readonly originalError: unknown
    public readonly timestamp: Date

    constructor(message: string, tool: string, originalError?: unknown) {
        super(message)
        this.name = 'MCPToolError'
        this.tool = tool
        this.originalError = originalError
        this.timestamp = new Date()
    }
}

/**
 * Thrown by `StateManager.getProjectId()` when no project can be resolved for
 * the current session — neither pinned via header, cached from a prior init,
 * nor derivable from the API key's scopes (e.g. an org-scoped key whose org
 * has no listable projects). Carries a multi-line message that walks the
 * agent through the available recovery tools, plus structured fields so
 * detection and formatting can be programmatic.
 */
export class MissingProjectContextError extends Error {
    public readonly organizationId: string | undefined

    constructor(options: { organizationId?: string | undefined } = {}) {
        super(formatMissingProjectContextMessage(options.organizationId))
        this.name = 'MissingProjectContextError'
        this.organizationId = options.organizationId
    }
}

function formatMissingProjectContextMessage(organizationId: string | undefined): string {
    const orgScopeLine = organizationId
        ? '\n\n' +
          `The session is currently scoped to organization \`${organizationId}\` but no project has been picked.`
        : ''

    return (
        'No PostHog project is selected for this MCP session, and a default could not be derived from your API key.' +
        orgScopeLine +
        '\n\n' +
        'To pick one (in order of preference):\n' +
        '1. Call `projects-get` to list projects you can access, then `switch-project` with the chosen project id.\n' +
        '2. If you already know the project id, call `switch-project { projectId: <id> }` directly.\n' +
        '3. (For MCP client maintainers) Pin a project at session start by sending the `x-posthog-project-id` header on the initialize request.' +
        '\n\n' +
        'If `projects-get` returns nothing, call `organizations-list` followed by `switch-organization` to pick a different org first — then retry `projects-get`.'
    )
}

/**
 * Thrown by `StateManager.getOrgID()` when no organization can be resolved for
 * the current session — neither pinned via header, cached from a prior init,
 * nor derivable from the API key's scopes or the active project. Throwing
 * (rather than returning `undefined`) prevents callers from interpolating
 * literal `"undefined"` into URLs like `/api/organizations/undefined/...`.
 */
export class MissingOrganizationContextError extends Error {
    constructor() {
        super(formatMissingOrganizationContextMessage())
        this.name = 'MissingOrganizationContextError'
    }
}

function formatMissingOrganizationContextMessage(): string {
    return (
        'No PostHog organization is selected for this MCP session, and a default could not be derived from your API key.' +
        '\n\n' +
        'To pick one (in order of preference):\n' +
        '1. Call `organizations-list` to list organizations you can access, then `switch-organization` with the chosen organization id.\n' +
        '2. (For MCP client maintainers) Pin an organization at session start by sending the `x-posthog-organization-id` header on the initialize request.'
    )
}

export interface PostHogValidationErrorOptions {
    detail: string
    attr: string | undefined
    code: string | undefined
    extra: Record<string, unknown> | undefined
    url: string
    method: string
}

/**
 * Thrown when the PostHog API rejects a request with a `validation_error`
 * body. Carries the structured `extra` payload (if any) so tool handlers can
 * surface information that doesn't fit in a single `detail` line — for
 * example, the HogQL metadata response attached to a failed /query/ call.
 */
export class PostHogValidationError extends Error {
    public readonly detail: string
    public readonly attr: string | undefined
    public readonly code: string | undefined
    public readonly extra: Record<string, unknown> | undefined
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogValidationErrorOptions) {
        const attr = options.attr ? ` (field: ${options.attr})` : ''
        super(`Validation error: ${options.detail}${attr}`)
        this.name = 'PostHogValidationError'
        this.detail = options.detail
        this.attr = options.attr
        this.code = options.code
        this.extra = options.extra
        this.url = options.url
        this.method = options.method
    }
}

export interface PostHogPermissionErrorOptions {
    detail: string
    missingScope?: string | undefined
    url: string
    method: string
}

/**
 * Thrown when the PostHog API rejects a request with HTTP 403 `permission_denied`.
 * Preserves the missing scope (when present) so the MCP layer can surface an
 * actionable remediation message instead of a generic failure.
 */
export class PostHogPermissionError extends Error {
    public readonly detail: string
    public readonly missingScope: string | undefined
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogPermissionErrorOptions) {
        const message = options.missingScope
            ? `Missing PostHog API scope: '${options.missingScope}'`
            : `PostHog API permission denied: ${options.detail}`
        super(message)
        this.name = 'PostHogPermissionError'
        this.detail = options.detail
        this.missingScope = options.missingScope
        this.url = options.url
        this.method = options.method
    }
}

/**
 * Creates an Error that wraps another error as its `cause`.
 * The tsconfig targets ES2021, which doesn't expose the ErrorOptions overload,
 * so set `cause` manually after construction. At runtime (Node 18+ / CF Workers)
 * the property still participates in cause-walking helpers like
 * `findPostHogPermissionError`.
 */
export function wrapError(message: string, cause: unknown): Error {
    const err = new Error(message) as Error & { cause?: unknown }
    err.cause = cause
    return err
}

const PERSONAL_API_KEY_DOCS_URL = 'https://posthog.com/docs/api#how-to-authenticate-with-the-posthog-api'

export function formatPermissionErrorMessage(error: PostHogPermissionError): string {
    if (error.missingScope) {
        return [
            `Missing PostHog API scope: '${error.missingScope}'`,
            '',
            `Your Personal API key is missing the '${error.missingScope}' scope, which is required to call ${error.method} ${error.url}.`,
            '',
            `To fix: edit the Personal API key in PostHog (User settings → Personal API keys) and add the '${error.missingScope}' scope. Alternatively, select the "MCP Server" scope preset which includes every scope the MCP needs.`,
            '',
            `See: ${PERSONAL_API_KEY_DOCS_URL}`,
        ].join('\n')
    }

    return [
        `PostHog API permission denied: ${error.detail}`,
        '',
        `The request to ${error.method} ${error.url} was rejected with HTTP 403. Verify that your API key, OAuth token, and user account have access to this project.`,
    ].join('\n')
}

/**
 * RFC 6750 §3.1: OAuth 2.0 Bearer challenge for 403 insufficient_scope. When
 * a missing scope is known, advertise it so OAuth-aware clients can prompt
 * for re-consent with the correct scope instead of reporting a generic error.
 */
export function buildInsufficientScopeChallenge(error: PostHogPermissionError): string {
    const parts = ['Bearer error="insufficient_scope"']
    const scope = sanitizeHeaderValue(error.missingScope)
    if (scope) {
        parts.push(`scope="${scope}"`)
    }
    // Replace double quotes to keep the challenge syntactically valid.
    const description = sanitizeHeaderValue(error.detail)?.replace(/"/g, "'")
    if (description) {
        parts.push(`error_description="${description}"`)
    }
    return parts.join(', ')
}

/**
 * Walk `Error.cause` chains to find a wrapped PostHogPermissionError.
 * Tool-level wrappers (e.g. `throw new Error("Failed to X: ...", { cause })`)
 * hide the underlying permission error, so callers must unwrap before acting.
 */
export function findPostHogPermissionError(error: unknown): PostHogPermissionError | undefined {
    let current: unknown = error
    const seen = new Set<unknown>()
    while (current && !seen.has(current)) {
        if (current instanceof PostHogPermissionError) {
            return current
        }
        seen.add(current)
        current = current instanceof Error ? (current as Error & { cause?: unknown }).cause : undefined
    }
    return undefined
}

/**
 * Handles tool errors and returns a structured error message.
 * Any errors that originate from the tool SHOULD be reported inside the result
 * object, with `isError` set to true, _not_ as an MCP protocol-level error
 * response. Otherwise, the LLM would not be able to see that an error occurred
 * and self-correct.
 *
 * @param error - The error object.
 * @param tool - Tool that caused the error.
 * @param distinctId - User's distinct ID for tracking.
 * @param sessionId - Session UUID for tracking.
 *
 * @returns A structured error message.
 */
export function handleToolError(error: any, tool?: string, distinctId?: string, sessionUuid?: string): CallToolResult {
    const toolName = tool || 'unknown'

    // Recoverable: agent can fix it via switch-project / projects-get. Skip
    // exception capture (this is expected user state, not a bug) and return the
    // typed error's pre-formatted multi-line message verbatim.
    if (error instanceof MissingProjectContextError || error instanceof MissingOrganizationContextError) {
        return {
            content: [
                {
                    type: 'text',
                    text: `Error: [${toolName}]: ${error.message}`,
                },
            ],
            isError: true,
        }
    }

    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        const properties: Record<string, any> = {
            team: 'growth',
            tool: toolName,
            is_permission_error: true,
            missing_scope: permissionError.missingScope,
            $exception_fingerprint: `posthog-permission-error:${toolName}:${permissionError.missingScope ?? 'unknown'}`,
        }

        if (sessionUuid) {
            properties.$session_id = sessionUuid
        }

        try {
            getPostHogClient().captureException(permissionError, distinctId, properties)
        } catch {
            // Never let observability break the request.
        }

        return {
            content: [
                {
                    type: 'text',
                    text: `Error: [${toolName}]: ${formatPermissionErrorMessage(permissionError)}`,
                },
            ],
            isError: true,
        }
    }

    const mcpError =
        error instanceof MCPToolError
            ? error
            : new MCPToolError(error instanceof Error ? error.message : String(error), toolName, error)

    const properties: Record<string, any> = {
        team: 'growth',
        tool: mcpError.tool,
        is_mcp_tool_error: error instanceof MCPToolError,
        $exception_fingerprint: mcpError.tool,
    }

    if (sessionUuid) {
        properties.$session_id = sessionUuid
    }

    try {
        getPostHogClient().captureException(mcpError, distinctId, properties)
    } catch {
        // Never let observability break the request.
    }

    return {
        content: [
            {
                type: 'text',
                text: `Error: [${mcpError.tool}]: ${mcpError.message}`,
            },
        ],
        isError: true,
    }
}
