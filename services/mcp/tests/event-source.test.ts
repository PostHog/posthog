import { describe, expect, it } from 'vitest'

import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'

// Every surface this server is allowed to stamp. `test_mcp_server_only_emits_sources_this_enum_knows`
// in `posthog/test/test_event_usage.py` holds the same list against Django's EventSource, so adding
// one here without adding it there fails on that side.
const SURFACES_THE_API_KNOWS = ['mcp', 'cli', 'wizard', 'slack', 'posthog_ai', 'posthog_code', 'self_driving']

const SANDBOX_SCOPES = ['insight:read', 'internal_run:read']
const CONSENTED_SCOPES = ['insight:read']

// Mirrors ARRAY_APP_CLIENT_ID_DEV and POSTHOG_AI_APP_CLIENT_ID_DEV in `posthog/temporal/oauth.py`.
const ARRAY_CLIENT_ID = 'DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ'
const POSTHOG_AI_CLIENT_ID = 'DD2ZLG6a2YEUtpPANSzSiIBPuUryYmbndLnKKUy1'
const SIGNALS_CLIENT_ID = 'xMT3Nejjbi4lUdhJLkzmCVJKFsx0JsHXdU0pIjl8'

describe('resolveEventSource', () => {
    it.each([
        ['a third-party agent has nothing to vouch for it', { mcpConsumer: 'cursor' }, EVENT_SOURCE.MCP],
        [
            'a self-declared first-party consumer without a server-minted token stays third-party',
            { mcpConsumer: 'slack', apiKeyScopes: ['insight:read'] },
            EVENT_SOURCE.MCP,
        ],
        ['the Slack app', { mcpConsumer: 'slack', apiKeyScopes: SANDBOX_SCOPES }, EVENT_SOURCE.SLACK],
        ['PostHog AI', { mcpConsumer: 'posthog_ai', apiKeyScopes: SANDBOX_SCOPES }, EVENT_SOURCE.POSTHOG_AI],
        [
            'a sandbox coding agent',
            { mcpConsumer: 'posthog-code', apiKeyScopes: SANDBOX_SCOPES },
            EVENT_SOURCE.POSTHOG_CODE,
        ],
        [
            'an unrecognized consumer on a server-minted token',
            { mcpConsumer: 'ops-agent', apiKeyScopes: SANDBOX_SCOPES },
            EVENT_SOURCE.MCP,
        ],
        ['the CLI, which has no first-party grant to gate on', { mcpConsumer: 'posthog-cli' }, EVENT_SOURCE.CLI],
        [
            'the wizard, whose user-agent outranks the MCP layer',
            { mcpConsumer: 'posthog-code', clientUserAgent: 'posthog/wizard 1.0' },
            EVENT_SOURCE.WIZARD,
        ],
        ['no consumer at all', {}, EVENT_SOURCE.MCP],
        [
            // The agent PostHog Desktop hosts authenticates with the user's consented token, so it
            // carries no `internal_run:read`. Only the OAuth application vouches for it, and Django
            // resolves the same request to posthog_code.
            'the local agent inside PostHog Desktop',
            { mcpConsumer: 'posthog-code', apiKeyScopes: CONSENTED_SCOPES, oauthClientId: ARRAY_CLIENT_ID },
            EVENT_SOURCE.POSTHOG_CODE,
        ],
        [
            'a PostHog AI token, whichever consumer it declares',
            { mcpConsumer: 'cursor', oauthClientId: POSTHOG_AI_CLIENT_ID },
            EVENT_SOURCE.POSTHOG_AI,
        ],
        [
            // Every Signals run declares the posthog-code consumer, so this row is what keeps it
            // from reading as a coding agent once it mints under the Signals application.
            'a Signals run, which declares the posthog-code consumer',
            { mcpConsumer: 'posthog-code', apiKeyScopes: SANDBOX_SCOPES, oauthClientId: SIGNALS_CLIENT_ID },
            EVENT_SOURCE.SELF_DRIVING,
        ],
        [
            'a third-party application declaring a first-party consumer',
            { mcpConsumer: 'slack', apiKeyScopes: CONSENTED_SCOPES, oauthClientId: 'some-third-party-client-id' },
            EVENT_SOURCE.MCP,
        ],
        [
            // A consumer naming an inherited Object member must not resolve to one.
            'a consumer borrowed from the prototype chain',
            { mcpConsumer: 'constructor', apiKeyScopes: SANDBOX_SCOPES },
            EVENT_SOURCE.MCP,
        ],
    ])('resolves %s', (_name, input, expected) => {
        expect(resolveEventSource(input)).toBe(expected)
    })

    it('emits only surfaces the PostHog API also knows', () => {
        // A source the API's EventSource does not carry drops out of every breakdown that joins
        // the MCP events with the product events they cause.
        expect(Object.values(EVENT_SOURCE).sort()).toEqual([...SURFACES_THE_API_KNOWS].sort())
    })
})
