// Decides how a missing OAuth scope reaches the client. A step-up token gets HTTP 403 with an
// RFC 6750 §3.1 challenge, but only from a check that runs before a tool does anything, because
// the client replays the request after re-consent. Everything else gets the tool error over
// HTTP 200 it always got, since other clients treat a 403 as a dead connection.

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
export function buildInsufficientScopeChallenge(requiredScopes: readonly string[]): string {
    // RFC 6749 §3.3 limits a scope token to these characters, so nothing that passes can
    // break out of the quoted header value.
    const scopes = [...new Set(requiredScopes)].filter((scope) => OAUTH_SCOPE_TOKEN.test(scope))
    const parts = ['Bearer error="insufficient_scope"']
    if (scopes.length > 0) {
        parts.push(`scope="${scopes.join(' ')}"`)
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

export function challengeStepUpBeforeRun(requiredScopes: readonly string[], supportsStepUp: boolean): void {
    if (supportsStepUp) {
        throw new InsufficientScopeError(requiredScopes)
    }
}

export function insufficientScopeResponse(body: string, challenge: string | undefined): Response {
    const headers: Record<string, string> = { 'Content-Type': 'text/plain; charset=utf-8' }
    if (challenge) {
        headers['WWW-Authenticate'] = challenge
    }
    return new Response(body, { status: 403, headers })
}
