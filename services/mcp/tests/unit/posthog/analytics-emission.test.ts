// End-to-end check that the dotcom analytics wiring survives the @posthog/mcp
// migration: drive the *real* SDK (not the global mock) through `initMcpAnalytics`
// and assert that the properties dotcom assembles — identity distinct_id, the
// `$mcp_*` context props, session tags, and `$groups` — actually land on the
// captured PostHog event, in both single-exec and full-roster registration modes.
import { vi } from 'vitest'

vi.unmock('@posthog/mcp-analytics')

// `initMcpAnalytics` resolves its PostHog client via `getPostHogClient()`. Swap
// it for a stub that records what the SDK hands to `posthog.capture()`.
const { capturedEvents, stubClient } = vi.hoisted(() => {
    const capturedEvents: { event: string; properties: Record<string, unknown>; distinctId?: string }[] = []
    return {
        capturedEvents,
        stubClient: {
            capture: (msg: { event: string; properties?: Record<string, unknown>; distinctId?: string }) => {
                capturedEvents.push({ event: msg.event, properties: msg.properties ?? {}, distinctId: msg.distinctId })
            },
            flush: async () => {},
            shutdown: async () => {},
        },
    }
})

vi.mock('@/lib/posthog/client', () => ({ getPostHogClient: () => stubClient }))

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { CallToolResultSchema } from '@modelcontextprotocol/sdk/types.js'
import { env } from 'cloudflare:workers'
import { beforeEach, describe, expect, it } from 'vitest'
import { z } from 'zod'

import { initMcpAnalytics, type IdentityProvider } from '@/lib/posthog/analytics'
import { createExecInnerToolCallResolver, createExecTool } from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

const mockContext = { getDistinctId: async () => 'user-123' } as unknown as Context

function createMockIdentity(): IdentityProvider {
    return {
        getDistinctId: async () => 'user-123',
        getSessionUuid: async () => 'session-uuid-456',
        getMcpClientName: async () => 'claude-code',
        getMcpClientVersion: async () => '1.2.3',
        getMcpProtocolVersion: async () => '2024-11-05',
        getMcpVendorClient: async () => 'ClaudeCode',
        getRegion: async () => 'us',
        getAnalyticsContext: async () => ({
            organizationId: 'org-789',
            projectId: 'proj-101',
            projectUuid: 'proj-uuid-101',
            projectName: 'Project 101',
        }),
        getClientUserAgent: async () => 'test-agent/1.0',
        getOAuthClientName: async () => 'PostHog Code',
        getReadOnly: async () => true,
        getTransport: async () => 'streamable-http',
        getMcpConsumer: async () => 'posthog-code',
        getMcpMode: async () => 'cli',
        getMcpSessionId: async () => 'mcp-session-abc',
        getMcpConversationId: async () => undefined,
    }
}

function makeTool(overrides: Partial<Tool<ZodObjectAny>>): Tool<ZodObjectAny> {
    return {
        name: 'mock-tool',
        title: 'Mock tool',
        description: 'A mock tool for testing',
        schema: z.object({}),
        scopes: [],
        annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
        handler: async () => 'ok',
        ...overrides,
    }
}

async function waitForEvent(
    predicate: (e: { event: string }) => boolean,
    timeoutMs = 1000
): Promise<{ event: string; properties: Record<string, unknown>; distinctId?: string } | undefined> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
        const match = capturedEvents.find(predicate)
        if (match) {
            return match
        }
        await new Promise((r) => setTimeout(r, 5))
    }
    return capturedEvents.find(predicate)
}

type Harness = { client: Client; cleanup: () => Promise<void> }

async function buildHarness(mode: 'single-exec' | 'full-roster'): Promise<Harness> {
    const tools = [makeTool({ name: 'execute-sql', description: 'Run a HogQL/SQL query against PostHog.' })]
    const server = new McpServer({ name: 'test-mcp', version: '1.0.0' })

    if (mode === 'single-exec') {
        const execTool = createExecTool(tools, mockContext, 'exec tool', 'command reference', undefined)
        server.registerTool(
            execTool.name,
            { title: execTool.title, description: execTool.description, inputSchema: execTool.schema.shape },
            (async (params: { command: string }) => ({
                content: [{ type: 'text' as const, text: String(await execTool.handler(mockContext, params)) }],
            })) as Parameters<typeof server.registerTool>[2]
        )
        await initMcpAnalytics(server, createMockIdentity(), {
            contextEnabled: true,
            reportMissingEnabled: false,
            resolveExecInnerToolCall: createExecInnerToolCallResolver(tools),
        })
    } else {
        const tool = tools[0]!
        server.registerTool(
            tool.name,
            { title: tool.title, description: tool.description, inputSchema: {} },
            (async () => ({ content: [{ type: 'text' as const, text: 'ok' }] })) as Parameters<
                typeof server.registerTool
            >[2]
        )
        await initMcpAnalytics(server, createMockIdentity(), { contextEnabled: true, reportMissingEnabled: false })
    }

    const client = new Client({ name: 'test-client', version: '1.0.0' }, { capabilities: {} })
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
    await Promise.all([client.connect(clientTransport), server.server.connect(serverTransport)])
    return {
        client,
        cleanup: async () => {
            await clientTransport.close?.()
            await serverTransport.close?.()
        },
    }
}

describe('dotcom analytics wiring end-to-end (real @posthog/mcp)', () => {
    beforeEach(() => {
        capturedEvents.length = 0
        env.POSTHOG_ANALYTICS_API_KEY = 'phc_test'
        env.POSTHOG_ANALYTICS_HOST = 'https://test.posthog.com'
    })

    it('full-roster: dotcom properties land on the captured $mcp_tool_call', async () => {
        const { client, cleanup } = await buildHarness('full-roster')
        try {
            await client.request(
                { method: 'tools/call', params: { name: 'execute-sql', arguments: { context: 'why' } } },
                CallToolResultSchema
            )

            const toolCall = await waitForEvent((e) => e.event === '$mcp_tool_call')
            expect(toolCall, '$mcp_tool_call should be captured').not.toBeUndefined()
            expect(toolCall?.distinctId).toBe('user-123')
            const p = toolCall!.properties
            expect(p.$mcp_tool_name).toBe('execute-sql')
            expect(p.$mcp_version).toBe(2)
            expect(p.$mcp_client_name).toBe('claude-code')
            expect(p.$mcp_organization_id).toBe('org-789')
            expect(p.$mcp_project_uuid).toBe('proj-uuid-101')
            expect(p.$session_id).toBe('session-uuid-456')
            expect(p.$ai_session_id).toBe('session-uuid-456')
            expect(p.$groups).toEqual({ organization: 'org-789', project: 'proj-uuid-101' })
        } finally {
            await cleanup()
        }
    })

    it('single-exec: same dotcom properties land, with the exec inner-tool props', async () => {
        const { client, cleanup } = await buildHarness('single-exec')
        try {
            await client.request(
                { method: 'tools/call', params: { name: 'exec', arguments: { command: 'call execute-sql {}' } } },
                CallToolResultSchema
            )

            const toolCall = await waitForEvent((e) => e.event === '$mcp_tool_call')
            expect(toolCall, '$mcp_tool_call should be captured').not.toBeUndefined()
            const p = toolCall!.properties
            expect(p.$mcp_tool_name).toBe('exec')
            expect(p.$mcp_organization_id).toBe('org-789')
            expect(p.$session_id).toBe('session-uuid-456')
            expect(p.$groups).toEqual({ organization: 'org-789', project: 'proj-uuid-101' })
            // exec-specific enrichment still resolves the real inner tool.
            expect(p.$mcp_exec_tool_call_name).toBe('execute-sql')
        } finally {
            await cleanup()
        }
    })

    it('emits an $identify event with the resolved distinct id', async () => {
        const { client, cleanup } = await buildHarness('full-roster')
        try {
            await client.request(
                { method: 'tools/call', params: { name: 'execute-sql', arguments: { context: 'why' } } },
                CallToolResultSchema
            )

            const identify = await waitForEvent((e) => e.event === '$identify')
            expect(identify, '$identify should be captured').not.toBeUndefined()
            expect(identify?.distinctId).toBe('user-123')
        } finally {
            await cleanup()
        }
    })
})
