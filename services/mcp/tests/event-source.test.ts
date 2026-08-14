import { describe, expect, it } from 'vitest'

import { EVENT_SOURCE, resolveEventSource } from '@/lib/event-source'
import eventSourcesContract from '@/lib/event-sources.json'

const SANDBOX_SCOPES = ['insight:read', 'internal_run:read']

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
