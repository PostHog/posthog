// Real end-to-end check that $mcp_exec_tool_call_name and
// $mcp_exec_tool_call_description actually land on the captured PostHog event
// when an agent runs `exec("call <tool> {}")`. Bypasses the global
// @posthog/mcp-analytics mock (set in tests/setup.ts) and drives the real SDK
// with a stub posthog-node client to capture events.
import { vi } from 'vitest'
vi.unmock('@posthog/mcp-analytics')

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { CallToolResultSchema } from '@modelcontextprotocol/sdk/types.js'
import { track } from '@posthog/mcp-analytics'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createExecInnerToolCallResolver, createExecTool } from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

type CapturedEvent = { event: string; properties: Record<string, unknown> }

type StubPostHogClient = {
    capture: (msg: { event: string; properties?: Record<string, unknown> }) => void
    flush: () => Promise<void>
    shutdown: () => Promise<void>
}

function makeStubPostHogClient(events: CapturedEvent[]): StubPostHogClient {
    return {
        capture: ({ event, properties }) => {
            events.push({ event, properties: properties ?? {} })
        },
        flush: async () => {},
        shutdown: async () => {},
    }
}

function makeTool(overrides: Partial<Tool<ZodObjectAny>>): Tool<ZodObjectAny> {
    return {
        name: 'mock-tool',
        title: 'Mock tool',
        description: 'A mock tool for testing',
        schema: z.object({}),
        scopes: [],
        annotations: {
            destructiveHint: false,
            idempotentHint: true,
            openWorldHint: false,
            readOnlyHint: true,
        },
        handler: async () => 'ok',
        ...overrides,
    }
}

const mockContext = { getDistinctId: async () => 'distinct-1' } as unknown as Context

type ExecHarness = {
    client: Client
    events: CapturedEvent[]
    cleanup: () => Promise<void>
}

async function buildExecHarness(allTools: Tool<ZodObjectAny>[]): Promise<ExecHarness> {
    const events: CapturedEvent[] = []
    const server = new McpServer({ name: 'test-mcp', version: '1.0.0' })

    const execTool = createExecTool(allTools, mockContext, 'exec tool', 'command reference', undefined)
    server.registerTool(
        execTool.name,
        { title: execTool.title, description: execTool.description, inputSchema: execTool.schema.shape },
        (async (params: { command: string }) => {
            const result = await execTool.handler(mockContext, params)
            return { content: [{ type: 'text' as const, text: String(result) }] }
        }) as Parameters<typeof server.registerTool>[2]
    )

    const resolveExecInnerToolCall = createExecInnerToolCallResolver(allTools)

    track(server, {
        apiKey: 'phc_test',
        posthogClient: makeStubPostHogClient(events),
        posthogOptions: { flushAt: 1, flushInterval: 0, host: 'https://test.posthog.com' },
        enableTracing: true,
        eventProperties: (request) => {
            const innerCall = resolveExecInnerToolCall(request)
            return innerCall
                ? {
                      $mcp_exec_tool_call_name: innerCall.name,
                      $mcp_exec_tool_call_description: innerCall.description,
                  }
                : {}
        },
    })

    const client = new Client({ name: 'test-client', version: '1.0.0' }, { capabilities: {} })
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
    await Promise.all([client.connect(clientTransport), server.server.connect(serverTransport)])

    return {
        client,
        events,
        cleanup: async () => {
            await clientTransport.close?.()
            await serverTransport.close?.()
        },
    }
}

// Poll the captured events for a matching record instead of sleeping a fixed
// duration — flushAt:1 makes capture effectively immediate, but timer-based
// waits are flake-prone under CI load.
async function waitForEvent(
    events: CapturedEvent[],
    predicate: (event: CapturedEvent) => boolean,
    timeoutMs = 1000
): Promise<CapturedEvent | undefined> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
        const match = events.find(predicate)
        if (match) {
            return match
        }
        await new Promise((resolve) => setTimeout(resolve, 5))
    }
    return events.find(predicate)
}

describe('$mcp_exec_tool_call_* end-to-end', () => {
    it('lands on the mcp_tool_call event when exec invokes a known inner tool', async () => {
        const allTools = [
            makeTool({ name: 'execute-sql', description: 'Run a HogQL/SQL query against PostHog.' }),
            makeTool({ name: 'feature-flag-get-all', description: 'List feature flags in the project.' }),
        ]
        const { client, events, cleanup } = await buildExecHarness(allTools)

        try {
            await client.request(
                {
                    method: 'tools/call',
                    params: { name: 'exec', arguments: { command: 'call execute-sql {}' } },
                },
                CallToolResultSchema
            )

            const toolCallEvent = await waitForEvent(events, (e) => e.event === 'mcp_tool_call')

            expect(toolCallEvent, 'mcp_tool_call event should be captured').not.toBeUndefined()
            expect(toolCallEvent?.properties.$mcp_tool_name).toBe('exec')
            // The SDK property reports the *outer* tool's description (exec) — which is
            // exactly the uninformative case the dotcom properties exist to fix.
            expect(toolCallEvent?.properties.$mcp_tool_description).toBe('exec tool')
            // The dotcom-side properties carry the real inner-tool name + description.
            expect(toolCallEvent?.properties.$mcp_exec_tool_call_name).toBe('execute-sql')
            expect(toolCallEvent?.properties.$mcp_exec_tool_call_description).toBe(
                'Run a HogQL/SQL query against PostHog.'
            )
        } finally {
            await cleanup()
        }
    })

    it('omits $mcp_exec_tool_call_* for non-call verbs', async () => {
        const allTools = [makeTool({ name: 'execute-sql', description: 'Run a HogQL/SQL query against PostHog.' })]
        const { client, events, cleanup } = await buildExecHarness(allTools)

        try {
            // `info` verb references a tool but doesn't invoke it — should NOT
            // emit the inner-call name or description.
            await client.request(
                {
                    method: 'tools/call',
                    params: { name: 'exec', arguments: { command: 'info execute-sql' } },
                },
                CallToolResultSchema
            )

            const toolCallEvent = await waitForEvent(events, (e) => e.event === 'mcp_tool_call')

            expect(toolCallEvent).not.toBeUndefined()
            expect(toolCallEvent?.properties).not.toHaveProperty('$mcp_exec_tool_call_name')
            expect(toolCallEvent?.properties).not.toHaveProperty('$mcp_exec_tool_call_description')
        } finally {
            await cleanup()
        }
    })
})
