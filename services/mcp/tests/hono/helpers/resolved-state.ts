import { vi } from 'vitest'

import type { ResolvedState } from '@/hono/request-state-resolver'

/**
 * A ResolvedState the tool-executor suites can mutate per case. Every field the
 * executor reads is present, so a test overrides only what its case is about.
 */
export function makeResolvedState(tools: { name: string }[], overrides: Partial<ResolvedState> = {}): ResolvedState {
    return {
        reqCtx: {
            cache: { get: vi.fn(), set: vi.fn() },
            safelyGetAnalyticsContext: vi.fn().mockResolvedValue(undefined),
            trackEvent: vi.fn(),
            trackContextSwitchEvent: vi.fn(),
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
            getEffectiveSessionUuid: vi.fn().mockResolvedValue(undefined),
        } as any,
        context: {
            api: {},
            cache: {},
            env: {},
            stateManager: {},
            sessionManager: {},
            getDistinctId: vi.fn(),
            trackEvent: vi.fn(),
        } as any,
        useSingleExec: false,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        oauthClientId: undefined,
        clientProfile: {
            capabilities: { supportsInstructions: true },
            isCliModeEnabled: vi.fn(() => false),
            isClaudeUiHost: vi.fn(() => false),
            isInlineExecUiHost: vi.fn(() => false),
            isClaudeChatHost: vi.fn(() => false),
        } as any,
        requestContext: {
            authMethod: 'personal_api_key',
            sessionId: 'sess-1',
            mcpClientName: 'test',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
            transport: 'streamable-http',
        },
        sessionContext: null,
        allTools: tools as any,
        scopeGatedTools: [],
        readOnlyGatedTools: [],
        flagGatedTools: [],
        gatewayToolsEnabled: false,
        distinctId: 'test-distinct-id',
        renderUiEnabled: false,
        metadata: undefined,
        metadataCompact: undefined,
        groupTypes: undefined,
        ...overrides,
    }
}
