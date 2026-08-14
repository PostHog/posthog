import { describe, expect, it } from 'vitest'

import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import eventSourcesContract from '@/lib/event-sources.json'

const SANDBOX_SCOPES = ['insight:read', 'internal_run:read']
const CONSENTED_SCOPES = ['insight:read']

// Mirrors ARRAY_APP_CLIENT_ID_DEV and POSTHOG_AI_APP_CLIENT_ID_DEV in `posthog/temporal/oauth.py`.
const ARRAY_CLIENT_ID = 'DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ'
const POSTHOG_AI_CLIENT_ID = 'DD2ZLG6a2YEUtpPANSzSiIBPuUryYmbndLnKKUy1'

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
        // The API asserts the same file against its own EventSource enum, so a value added on
        // one side without the other fails on that side rather than silently emitting a source
        // that drops out of every joined breakdown.
        expect(Object.values(EVENT_SOURCE).sort()).toEqual([...eventSourcesContract.sources].sort())
    })
})
