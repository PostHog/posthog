/**
 * Deep-link helpers for the secrets editor.
 *
 * The concierge agent (and any other tool that needs the user to set or
 * rotate a secret) builds a URL pointing at the per-agent secrets editor
 * via these helpers. Two delivery shapes:
 *
 *   1. **Client-side tool**: the agent has a registered handler that
 *      receives `{ agentSlug, secret, sessionId }`, calls
 *      `router.push(buildSecretEditUrl(...))`, and the user lands on
 *      the editor in the same tab. The session id lets the editor fire
 *      a callback event when the user saves.
 *   2. **URL handoff**: when the client tool isn't available (e.g.
 *      headless / non-browser MCP client), the agent emits a markdown
 *      link via `buildSecretEditUrl(...)` in its chat message. The user
 *      clicks, sets the secret, the page emits the same callback event.
 *
 * The callback event flows back to the dock's chat runner so the agent
 * receives a synthetic "secret was set" message and resumes its plan.
 * Both delivery shapes share the same URL contract, so the agent's plan
 * doesn't change whether the client tool exists or not.
 */

export interface SecretEditUrlOpts {
    /** Agent slug — owns the secret. */
    agentSlug: string
    /** Env variable name (e.g. `ANTHROPIC_KEY`). */
    secret: string
    /**
     * Session id of the conversation that's waiting on the user. When
     * set, the editor dispatches `SECRET_SET_EVENT` with this id on
     * save; the dock's runner listens, sees the id matches its active
     * session, and posts a follow-up message so the agent resumes.
     *
     * Omit for "just send the user to the editor" — no callback flow.
     */
    callbackSessionId?: string
}

/**
 * Build the in-app URL pointing at the editor for a specific secret.
 *
 * Path: `/agents/<slug>/connections` with `?edit_secret=<KEY>` and an
 * optional `callback_session=<id>`. Path-only — the agent / dock
 * supplies the origin if it needs an absolute URL.
 */
export function buildSecretEditUrl({ agentSlug, secret, callbackSessionId }: SecretEditUrlOpts): string {
    const params = new URLSearchParams({ edit_secret: secret })
    if (callbackSessionId) {
        params.set('callback_session', callbackSessionId)
    }
    return `/agents/${encodeURIComponent(agentSlug)}/connections?${params.toString()}`
}

/**
 * Custom window event the editor dispatches after a successful save or
 * clear. The dock's chat runner listens for this and posts a synthetic
 * follow-up into the matching session so the agent receives a
 * "user finished, here's the outcome" turn without the user typing.
 *
 * Why a window event (vs a direct call into the dock store)?
 *   - The editor and the dock are mounted in separate React trees today.
 *   - Decoupling means the editor can be opened from any context
 *     (a notification, a tool result render) without needing dock-store
 *     access.
 *   - Pages opened in a new tab won't have a dock listener — that's
 *     fine; the agent then simply doesn't get the callback. The user
 *     can always tell the agent themselves.
 */
export const SECRET_SET_EVENT = 'agent-console:secret-set'

export interface SecretSetEventDetail {
    agentSlug: string
    secret: string
    action: 'set' | 'cleared'
    /** Echoed from `callback_session` in the URL, when one was present. */
    sessionId: string | null
}

export function dispatchSecretSetEvent(detail: SecretSetEventDetail): void {
    if (typeof window === 'undefined') {
        return
    }
    window.dispatchEvent(new CustomEvent<SecretSetEventDetail>(SECRET_SET_EVENT, { detail }))
}

/**
 * Render a human-friendly system message describing what the user did.
 * Used by the dock's auto-send on the callback event.
 */
export function describeSecretCallback(detail: SecretSetEventDetail): string {
    const verb = detail.action === 'set' ? 'set' : 'cleared'
    return `[system] User ${verb} secret \`${detail.secret}\` on agent \`${detail.agentSlug}\`. Continue.`
}
