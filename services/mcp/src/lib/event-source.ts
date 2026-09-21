// Which PostHog surface a request came from, stamped as `source` so the MCP server's own
// events sit in the same breakdown as the product events they cause.
//
// The vocabulary is Django's: `EventSource` in `posthog/event_usage.py` owns it, and this is a
// subset. `tests/event-source.test.ts` pins the values below, and the API holds the same list in
// `test_mcp_server_only_emits_sources_this_enum_knows`, so a surface added on one side alone fails
// on the other.

import { POSTHOG_CODE_CONSUMER } from './client-detection'

export const EVENT_SOURCE = {
    MCP: 'mcp',
    CLI: 'cli',
    WIZARD: 'wizard',
    SLACK: 'slack',
    POSTHOG_AI: 'posthog_ai',
    POSTHOG_CODE: 'posthog_code',
    SELF_DRIVING: 'self_driving',
} as const

export type EventSource = (typeof EVENT_SOURCE)[keyof typeof EVENT_SOURCE]

const CLI_CONSUMER = 'posthog-cli'
const WIZARD_USER_AGENT_FRAGMENT = 'posthog/wizard'

// Minted server-side only and rejected by every user-facing scope validator, so a token
// carrying it is provably one of PostHog's own agents rather than a third party naming
// itself one. See INTERNAL_SCOPES in `posthog/temporal/oauth.py`.
const INTERNAL_RUN_SCOPE = 'internal_run:read'

// The OAuth applications PostHog controls, mirroring POSTHOG_DESKTOP_OAUTH_CLIENT_IDS,
// POSTHOG_AI_OAUTH_APP_CLIENT_IDS and SIGNALS_OAUTH_APP_CLIENT_IDS in
// `posthog/temporal/oauth.py`, which owns them. A client id reaches this server through token
// introspection rather than a header, so unlike `x-posthog-mcp-consumer` the caller cannot set
// it for itself.
const POSTHOG_AI_OAUTH_CLIENT_IDS = new Set([
    'N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu',
    '0Lizwa3mFSlBuEEQ8V8FMJlskUXpDuSmoEdhzxyi',
    'DD2ZLG6a2YEUtpPANSzSiIBPuUryYmbndLnKKUy1',
])

const SIGNALS_OAUTH_CLIENT_IDS = new Set([
    'jpSRPhGBBbDGpKprit9bgJEuo6oUTa8ULymqf8PE',
    'nqZsiFEbu1fCWDK3r8QtSGwKmmANxVIgfZmTXywk',
    'xMT3Nejjbi4lUdhJLkzmCVJKFsx0JsHXdU0pIjl8',
])

const FIRST_PARTY_OAUTH_CLIENT_IDS = new Set([
    'HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W',
    'AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9',
    'DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ',
    'a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm',
    '1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU',
])

/**
 * Whether one of PostHog's own OAuth applications vouches for this request.
 *
 * The client id is what Django gates on, so it is the signal that makes the two sides agree.
 * `internal_run:read` stays as a second route because it is minted server-side only, which
 * makes it proof of a first-party token on its own, and it still resolves the surface when
 * introspection has not populated the client id for this request.
 */
function isFirstPartyCaller(input: EventSourceInput): boolean {
    if (input.oauthClientId && FIRST_PARTY_OAUTH_CLIENT_IDS.has(input.oauthClientId)) {
        return true
    }
    return input.apiKeyScopes?.includes(INTERNAL_RUN_SCOPE) ?? false
}

// What a first-party caller declares in `x-posthog-mcp-consumer` when it wraps this server.
// A Map rather than an object literal because the key is caller-supplied: indexing an object
// with `constructor` or `toString` returns an inherited function, which is truthy and so
// survives a `??` fallback.
const FIRST_PARTY_CONSUMER_TO_SOURCE = new Map<string, EventSource>([
    ['slack', EVENT_SOURCE.SLACK],
    ['posthog_ai', EVENT_SOURCE.POSTHOG_AI],
    [POSTHOG_CODE_CONSUMER, EVENT_SOURCE.POSTHOG_CODE],
])

export interface EventSourceInput {
    mcpConsumer?: string | undefined
    clientUserAgent?: string | undefined
    apiKeyScopes?: readonly string[] | undefined
    oauthClientId?: string | undefined
}

/**
 * Resolve the surface behind an MCP request.
 *
 * Mirrors `get_event_source` in `posthog/event_usage.py`, with one remaining gap. Django can
 * tell the interactive desktop app apart from the agents that share its OAuth application by
 * reading refresh-token lineage out of the database, which this server cannot do. A first-party
 * request that declares no consumer therefore resolves to `desktop` on the API events and `mcp`
 * on the `$mcp_*` events from the same call. Nothing routes the app through this server today,
 * so the gap is not reachable in practice; the `source` taxonomy entry records it.
 *
 * Ends at `mcp`, meaning a third-party agent, whenever nothing vouches for the declared consumer.
 */
export function resolveEventSource(input: EventSourceInput): EventSource {
    // A token minted against the PostHog AI application is authoritative, which is the same
    // early return `get_event_source` makes before it looks at any header.
    if (input.oauthClientId && POSTHOG_AI_OAUTH_CLIENT_IDS.has(input.oauthClientId)) {
        return EVENT_SOURCE.POSTHOG_AI
    }
    // Signals resolves the same way, and has to be settled before the consumer branches: a
    // Signals run declares the `posthog-code` consumer, so the application it minted under is
    // the only thing separating it from a coding agent.
    if (input.oauthClientId && SIGNALS_OAUTH_CLIENT_IDS.has(input.oauthClientId)) {
        return EVENT_SOURCE.SELF_DRIVING
    }
    // Matches Django: the outer caller's user-agent wins over anything the MCP layer says.
    if (input.clientUserAgent?.includes(WIZARD_USER_AGENT_FRAGMENT)) {
        return EVENT_SOURCE.WIZARD
    }
    // The CLI authenticates with a personal API key, so there is no first-party grant to
    // vouch for it. Django honors it ungated for the same reason.
    if (input.mcpConsumer === CLI_CONSUMER) {
        return EVENT_SOURCE.CLI
    }
    if (!input.mcpConsumer || !isFirstPartyCaller(input)) {
        return EVENT_SOURCE.MCP
    }
    return FIRST_PARTY_CONSUMER_TO_SOURCE.get(input.mcpConsumer) ?? EVENT_SOURCE.MCP
}
