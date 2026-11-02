// The one place that decides how a missing OAuth scope reaches the client.
//
// A token whose OAuth app supports step-up gets HTTP 403 with an RFC 6750 §3.1
// `insufficient_scope` challenge, but only from a check that runs before the tool does
// anything. The MCP spec's step-up flow has the client union the challenge's `scope` with
// the scopes it holds, ask the user for that union, and replay the request. A replay after
// the tool already wrote something would write it twice, so a missing scope that the API
// reports while the tool runs becomes the tool error for every token.
//
// Every other case gets the tool error over HTTP 200, because a client that does not handle
// the challenge treats a 403 as a dead connection. The tool error carries the challenge in
// `_meta`, which ChatGPT reads and other clients ignore.

import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

const WWW_AUTHENTICATE_META_KEY = 'mcp/www_authenticate'

const OAUTH_SCOPE_TOKEN = /^[\x21\x23-\x5B\x5D-\x7E]+$/

/** Thrown in place of a tool result so the transport answers the request with HTTP 403. */
export class InsufficientScopeError extends Error {
    public readonly challenge: string
    public readonly requiredScopes: readonly string[]

    constructor(requiredScopes: readonly string[]) {
        super(`This request needs the PostHog scopes: ${requiredScopes.join(', ')}`)
        this.name = 'InsufficientScopeError'
        this.challenge = buildInsufficientScopeChallenge(requiredScopes)
        this.requiredScopes = requiredScopes
    }
}

// No `resource_metadata`: Hono sits behind the worker proxy and does not know the origin the
// client connected to, so the worker adds it to the 403 (see `withResourceMetadata`).
export function buildInsufficientScopeChallenge(
    requiredScopes: readonly string[],
    { withDescription = false }: { withDescription?: boolean } = {}
): string {
    // RFC 6749 §3.3 limits a scope token to these characters, so nothing that passes can
    // break out of the quoted header value.
    const scopes = [...new Set(requiredScopes)].filter((scope) => OAUTH_SCOPE_TOKEN.test(scope))
    const parts = ['Bearer error="insufficient_scope"']
    if (scopes.length > 0) {
        parts.push(`scope="${scopes.join(' ')}"`)
    }
    if (withDescription) {
        parts.push(`error_description="Reconnect PostHog and approve these scopes: ${scopes.join(' ')}"`)
    }
    return parts.join(', ')
}

export function parseInsufficientScopeChallenge(header: string | null | undefined): string[] | undefined {
    if (!header || !/error="insufficient_scope"/.test(header)) {
        return undefined
    }
    const scope = /(?:^|[\s,])scope="([^"]*)"/.exec(header)?.[1]
    return scope ? scope.split(' ').filter(Boolean) : []
}

/**
 * Called before a tool call does anything, including bookkeeping such as analytics or guidance.
 * Throws `InsufficientScopeError` for a step-up token, which the transport answers with HTTP 403.
 */
export function challengeStepUpBeforeRun(requiredScopes: readonly string[], supportsStepUp: boolean): void {
    if (supportsStepUp) {
        throw new InsufficientScopeError(requiredScopes)
    }
}

export function missingScopeToolResult(requiredScopes: readonly string[], toolError: CallToolResult): CallToolResult {
    // OpenAI's Apps SDK documents this key as a list of challenges, each with `error` and
    // `error_description`.
    const challenges = [buildInsufficientScopeChallenge(requiredScopes, { withDescription: true })]
    return { ...toolError, _meta: { ...toolError._meta, [WWW_AUTHENTICATE_META_KEY]: challenges } }
}

export function insufficientScopeResponse(body: string, challenge: string | undefined): Response {
    const headers: Record<string, string> = { 'Content-Type': 'text/plain; charset=utf-8' }
    if (challenge) {
        headers['WWW-Authenticate'] = challenge
    }
    return new Response(body, { status: 403, headers })
}
