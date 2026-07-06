import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

import { getPostHogClient } from '@/lib/posthog'
import { getToolRecoveryHint } from '@/lib/tool-error-hints'
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

/**
 * Thrown when MCP-side schema validation rejects a tool call's input before
 * any handler runs (the exec `call` path). The message is pre-formatted by
 * `formatInputValidationError` and already names the offending field(s), so
 * `handleToolError` returns it verbatim — capturing it as an exception would
 * mint a per-tool error tracking issue for every agent slip-up, the same
 * noise problem the 4xx short-circuit exists to prevent.
 */
export class ToolInputValidationError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ToolInputValidationError'
    }
}

export interface PostHogApiErrorOptions {
    status: number
    statusText: string
    body: string
    url: string
    method: string
    message?: string
}

/**
 * Thrown when the PostHog API rejects a request with a non-success status that
 * isn't already handled by a more specific subclass (PostHogPermissionError,
 * PostHogValidationError). Carries the status code so callers can distinguish
 * recoverable agent-input errors (4xx) from genuine service failures (5xx).
 *
 * Background: an LLM agent passing a placeholder UUID to an MCP tool produced
 * a 404, and `handleToolError` captured it as a PostHog exception fingerprinted
 * by tool name — creating a brand-new error tracking issue per tool every time
 * an agent fumbled a parameter. Keying off `status` here lets `handleToolError`
 * short-circuit 4xx without losing visibility into real 5xx failures.
 */
export class PostHogApiError extends Error {
    public readonly status: number
    public readonly statusText: string
    public readonly body: string
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogApiErrorOptions) {
        super(options.message ?? buildDefaultApiErrorMessage(options))
        this.name = 'PostHogApiError'
        this.status = options.status
        this.statusText = options.statusText
        this.body = options.body
        this.url = options.url
        this.method = options.method
    }
}

function buildDefaultApiErrorMessage(options: PostHogApiErrorOptions): string {
    return `Request failed:\nURL: ${options.method} ${options.url}\nStatus Code: ${options.status} (${options.statusText})\nError Message: ${options.body}`
}

export interface PostHogRateLimitErrorOptions {
    body: string
    url: string
    method: string
    retryAfterSeconds: number | null
}

/**
 * Thrown when the PostHog API responds with HTTP 429. Never retried inside the
 * MCP server: sleeping here keeps the client's request open and lets pending
 * work pile up behind it, so the rate limit is surfaced immediately with the
 * server's Retry-After hint and the client decides when to retry.
 */
export class PostHogRateLimitError extends PostHogApiError {
    public readonly retryAfterSeconds: number | null

    constructor(options: PostHogRateLimitErrorOptions) {
        const retryHint = options.retryAfterSeconds !== null ? ` Retry after ${options.retryAfterSeconds} seconds.` : ''
        super({
            status: 429,
            statusText: 'Too Many Requests',
            body: options.body,
            url: options.url,
            method: options.method,
            message: `PostHog API rate limit exceeded (429) on ${options.method} ${options.url}.${retryHint}`,
        })
        this.name = 'PostHogRateLimitError'
        this.retryAfterSeconds = options.retryAfterSeconds
    }
}

/**
 * Parses a Retry-After header into whole seconds. Returns null for missing
 * headers, HTTP-date values, and bogus negatives.
 */
export function parseRetryAfterSeconds(header: string | null): number | null {
    if (!header) {
        return null
    }
    const seconds = Number.parseInt(header, 10)
    return Number.isNaN(seconds) || seconds < 0 ? null : seconds
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
    const callTarget = error.method && error.url ? `${error.method} ${error.url}` : 'this MCP request'
    if (error.missingScope) {
        return [
            `Missing PostHog API scope: '${error.missingScope}'`,
            '',
            `Your Personal API key is missing the '${error.missingScope}' scope, which is required to call ${callTarget}.`,
            '',
            `To fix: edit the Personal API key in PostHog (User settings → Personal API keys) and add the '${error.missingScope}' scope. Alternatively, select the "MCP Server" scope preset which includes every scope the MCP needs.`,
            '',
            `See: ${PERSONAL_API_KEY_DOCS_URL}`,
        ].join('\n')
    }

    return [
        `PostHog API permission denied: ${error.detail}`,
        '',
        `The request to ${callTarget} was rejected with HTTP 403. Verify that your API key, OAuth token, and user account have access to this project.`,
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

// Literal message shape produced by `new PostHogPermissionError({...})`. We
// reconstruct from this when the error has crossed a boundary that strips
// `cause` and the custom subclass prototype — see the fallback in
// `findPostHogPermissionError` for the full reasoning.
const MISSING_SCOPE_MESSAGE_PATTERN = /Missing PostHog API scope: ['"]([^'"]+)['"]/

/**
 * Walk `Error.cause` chains to find a wrapped PostHogPermissionError.
 * Tool-level wrappers (e.g. `throw new Error("Failed to X: ...", { cause })`)
 * hide the underlying permission error, so callers must unwrap before acting.
 *
 * Fallback for the Cloudflare Durable Object RPC boundary: errors thrown
 * inside the DO arrive in the worker as plain Errors — `cause`, the
 * PostHogPermissionError prototype, and any custom own-properties have all
 * been stripped by the cross-isolate serializer, leaving just `name`,
 * `message`, and `stack`. Without this fallback, a permission error from
 * `_fetchUser` (or any other init-time API call) gets mapped to an opaque
 * 500 in `onCatchErrorHandler` and OAuth-aware MCP clients never see the
 * 403 + `WWW-Authenticate: insufficient_scope` they need to re-consent.
 *
 * The literal `Missing PostHog API scope: 'X'` shape produced by the
 * `PostHogPermissionError` constructor is the one piece of information that
 * does survive — we re-synthesize a typed error from it. `url`/`method`
 * are not recoverable from the message alone; `formatPermissionErrorMessage`
 * handles the empty case.
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

    if (error instanceof Error && typeof error.message === 'string') {
        const match = MISSING_SCOPE_MESSAGE_PATTERN.exec(error.message)
        if (match) {
            const missingScope = match[1]!
            return new PostHogPermissionError({
                detail: `API key missing required scope '${missingScope}'`,
                missingScope,
                url: '',
                method: '',
            })
        }
    }

    return undefined
}

/**
 * Walks `Error.cause` chains to find a wrapped PostHogApiError or
 * PostHogValidationError. Tool-level wrappers (e.g. `throw new Error("Failed
 * to X: ...", { cause })`) hide the underlying typed error, so callers must
 * unwrap before classifying the failure.
 */
export function findRecoverableApiError(error: unknown): PostHogApiError | PostHogValidationError | undefined {
    let current: unknown = error
    const seen = new Set<unknown>()
    while (current && !seen.has(current)) {
        if (current instanceof PostHogApiError || current instanceof PostHogValidationError) {
            return current
        }
        seen.add(current)
        current = current instanceof Error ? (current as Error & { cause?: unknown }).cause : undefined
    }
    return undefined
}

/**
 * True for upstream failures that are transient and safe to retry or tolerate:
 * 5xx service errors and 429 rate limits (PostHogRateLimitError extends
 * PostHogApiError with status 429). Unwraps `cause` chains first, so a wrapped
 * error still classifies. Used to keep restarting-backend blips out of error
 * tracking and to degrade gracefully instead of hard-failing the request.
 */
export function isTransientApiError(error: unknown): boolean {
    const apiError = findRecoverableApiError(error)
    if (apiError instanceof PostHogApiError) {
        return apiError.status >= 500 || apiError.status === 429
    }
    return false
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

    // Recoverable: input rejected by the tool's schema before any handler ran —
    // an agent slip-up, not a bug. The message already names the offending
    // field(s); skip exception capture like the API 4xx branch below.
    if (error instanceof ToolInputValidationError) {
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

    // Recoverable: 4xx responses from the PostHog API (and validation errors)
    // are agent-input failures — the LLM passed a bad id, a stale UUID, or a
    // value the serializer rejected. Returning the typed error message to the
    // LLM lets it self-correct on the next turn. Capturing these as exceptions
    // — fingerprinted by tool name — would create a fresh error tracking issue
    // for every agent slip-up. Reserve `captureException` for 5xx and
    // unexpected non-HTTP errors, which are genuinely actionable for engineers.
    const recoverableApiError = findRecoverableApiError(error)
    if (recoverableApiError) {
        const isFourXx =
            recoverableApiError instanceof PostHogValidationError ||
            (recoverableApiError.status >= 400 && recoverableApiError.status < 500)
        if (isFourXx) {
            return {
                content: [
                    {
                        type: 'text',
                        text: `Error: [${toolName}]: ${recoverableApiError.message}`,
                    },
                ],
                isError: true,
            }
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

    // A 5xx returns an opaque server body the agent can't act on. When the
    // failed endpoint has a known recovery path (e.g. a logs query that scanned
    // too much data), append a short "here's how to recover" footer so the agent
    // narrows and retries instead of re-issuing the same failing call.
    // `recoverableApiError` was unwrapped from any `cause` chain above; only 5xx
    // reach here (4xx short-circuited earlier).
    const recoveryHint =
        recoverableApiError instanceof PostHogApiError
            ? getToolRecoveryHint({ url: recoverableApiError.url, status: recoverableApiError.status })
            : undefined

    return {
        content: [
            {
                type: 'text',
                text: `Error: [${mcpError.tool}]: ${mcpError.message}${recoveryHint ? `\n\n${recoveryHint}` : ''}`,
            },
        ],
        isError: true,
    }
}
