// Which PostHog surface a request came from, stamped as `source` so the MCP server's own
// events sit in the same breakdown as the product events they cause.
//
// The vocabulary is Django's: `EventSource` in `posthog/event_usage.py` is the source of
// truth, and `test_event_source_vocabulary_matches_django` keeps this subset honest against
// the checked-in list both sides read.

import { POSTHOG_CODE_CONSUMER } from './client-detection'

export const EVENT_SOURCE = {
    MCP: 'mcp',
    CLI: 'cli',
    WIZARD: 'wizard',
    SLACK: 'slack',
    POSTHOG_AI: 'posthog_ai',
    POSTHOG_CODE: 'posthog_code',
} as const

export type EventSource = (typeof EVENT_SOURCE)[keyof typeof EVENT_SOURCE]

const CLI_CONSUMER = 'posthog-cli'
const WIZARD_USER_AGENT_FRAGMENT = 'posthog/wizard'

// Minted server-side only and rejected by every user-facing scope validator, so a token
// carrying it is provably one of PostHog's own agents rather than a third party naming
// itself one. See INTERNAL_SCOPES in `posthog/temporal/oauth.py`.
const INTERNAL_RUN_SCOPE = 'internal_run:read'

// What a first-party caller declares in `x-posthog-mcp-consumer` when it wraps this server.
const FIRST_PARTY_CONSUMER_TO_SOURCE: Record<string, EventSource> = {
    slack: EVENT_SOURCE.SLACK,
    posthog_ai: EVENT_SOURCE.POSTHOG_AI,
    [POSTHOG_CODE_CONSUMER]: EVENT_SOURCE.POSTHOG_CODE,
}

export interface EventSourceInput {
    mcpConsumer?: string | undefined
    clientUserAgent?: string | undefined
    apiKeyScopes?: readonly string[] | undefined
}

/**
 * Resolve the surface behind an MCP request.
 *
 * Mirrors `get_event_source` in `posthog/event_usage.py`, with one deliberate gap. Django
 * separates the interactive desktop app from the headless agents by inspecting the OAuth
 * grant — both declare the same consumer, and only a database read tells them apart. This
 * server never sees that, so the desktop app resolves to `mcp` here while the API events
 * from the same request resolve to `desktop`. Closing it needs a signal the worker can see
 * (the OAuth `client_id` in token introspection would be enough).
 *
 * Ends at `mcp` — a third-party agent — whenever nothing vouches for the declared consumer.
 */
export function resolveEventSource(input: EventSourceInput): EventSource {
    // Matches Django: the outer caller's user-agent wins over anything the MCP layer says.
    if (input.clientUserAgent?.includes(WIZARD_USER_AGENT_FRAGMENT)) {
        return EVENT_SOURCE.WIZARD
    }
    // The CLI authenticates with a personal API key, so there is no first-party grant to
    // vouch for it. Django honors it ungated for the same reason.
    if (input.mcpConsumer === CLI_CONSUMER) {
        return EVENT_SOURCE.CLI
    }
    if (!input.mcpConsumer || !input.apiKeyScopes?.includes(INTERNAL_RUN_SCOPE)) {
        return EVENT_SOURCE.MCP
    }
    return FIRST_PARTY_CONSUMER_TO_SOURCE[input.mcpConsumer] ?? EVENT_SOURCE.MCP
}
