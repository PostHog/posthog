import { beforeEach, describe, expect, it, vi } from 'vitest'

const { batches } = vi.hoisted(() => ({ batches: [] as string[] }))

vi.mock('@/lib/posthog', async () => {
    const { PostHogMCP } = await import('@posthog/mcp-analytics')
    const client = new PostHogMCP('phc_test', {
        host: 'https://capture.example.com',
        flushAt: 1,
        flushInterval: 0,
        disableCompression: true,
        captureModel: true,
        fetch: async (_url, options) => {
            batches.push(String(options.body))
            return { status: 200, text: async () => '{}', json: async () => ({}) }
        },
    })
    return { getPostHogClient: () => client }
})

import { trackToolCall, trackToolSpan } from '@/hono/analytics'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { getPostHogClient } from '@/lib/posthog'

function makeState(): ResolvedState {
    return {
        reqCtx: {
            safelyGetAnalyticsContext: async () => undefined,
            getSessionUuid: async () => 'session-uuid',
            getEffectiveSessionUuid: async () => 'session-uuid',
        } as any,
        context: { stateManager: {} } as any,
        useSingleExec: true,
        splitWrites: false,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        oauthClientId: undefined,
        clientProfile: {} as any,
        requestContext: {
            authMethod: 'personal_api_key',
            sessionId: 'sess-1',
            requestStartTime: Date.now(),
            transport: 'streamable-http',
            mode: 'cli',
            region: 'us',
        } as any,
        sessionContext: {} as any,
        allTools: [],
        scopeGatedTools: [],
        findScopeGatedTool: () => undefined,
        supportsStepUp: false,
        flagGatedTools: [],
        gatewayToolsEnabled: false,
        distinctId: 'distinct-id',
        renderUiEnabled: false,
    }
}

describe('MCP analytics for suppression tools', () => {
    beforeEach(() => {
        batches.length = 0
    })

    it.each([
        ['a suppression search', 'suppressions-list', { search: 'ada@example.com' }],
        ['a suppression removal', 'suppressions-remove', { identifiers: ['ada@example.com'] }],
        [
            'a suppression removal through exec',
            'exec',
            { command: 'call suppressions-remove {"identifiers":["ada@example.com"]}' },
        ],
    ])('sends the events for %s without the address', async (_case, toolName, parameters) => {
        const response = { removed: ['ada@example.com'], not_found: [] }

        await trackToolCall(toolName, 12, false, makeState(), undefined, { parameters, response })
        await trackToolSpan(toolName, makeState(), {
            durationMs: 12,
            isError: false,
            input: parameters,
            output: response,
        })
        await getPostHogClient().flush()

        const sent = batches.join('\n')
        expect(sent).toContain('"$mcp_tool_call"')
        expect(sent).not.toContain('ada@example.com')
    })
})
