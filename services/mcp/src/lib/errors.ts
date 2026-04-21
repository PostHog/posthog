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

        getPostHogClient().captureException(permissionError, distinctId, properties)

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

    getPostHogClient().captureException(mcpError, distinctId, properties)

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
