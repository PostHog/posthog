// Real end-to-end check that $mcp_exec_tool_call_description actually lands
// on the captured PostHog event when an agent runs `exec("call <tool> {}")`.
// Bypasses the global @posthog/mcp-analytics mock (set in tests/setup.ts) and
// drives the real SDK with a stub posthog-node client to capture events.
import { vi } from 'vitest'
vi.unmock('@posthog/mcp-analytics')

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { CallToolResultSchema } from '@modelcontextprotocol/sdk/types.js'
import { track } from '@posthog/mcp-analytics'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createExecTool, parseExecCallInnerToolName } from '@/tools/exec'
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

describe('$mcp_exec_tool_call_description end-to-end', () => {
    it('lands on the mcp_tool_call event when exec invokes a known inner tool', async () => {
        const allTools = [
            makeTool({ name: 'execute-sql', description: 'Run a HogQL/SQL query against PostHog.' }),
            makeTool({ name: 'feature-flag-get-all', description: 'List feature flags in the project.' }),
        ]

        const events: CapturedEvent[] = []

        const server = new McpServer({ name: 'test-mcp', version: '1.0.0' })

        // Build the resolver exactly the way mcp.ts wires it in single-exec mode.
        const resolveExecInnerToolDescription = (request: unknown): string | undefined => {
            const params = (request as { params?: { name?: unknown; arguments?: { command?: unknown } } })?.params
            if (params?.name !== 'exec' || typeof params.arguments?.command !== 'string') {
                return
            }
            const innerName = parseExecCallInnerToolName(params.arguments.command)
            if (!innerName) {
                return
            }
            return allTools.find((t) => t.name === innerName)?.description
        }

        // Register the exec tool with the real allTools so its `call` verb
        // dispatches to mock-tool/execute-sql.
        const execTool = createExecTool(allTools, mockContext, 'exec tool', 'command reference', undefined)
        server.registerTool(
            execTool.name,
            { title: execTool.title, description: execTool.description, inputSchema: execTool.schema.shape },
            (async (params: { command: string }) => {
                const result = await execTool.handler(mockContext, params)
                return { content: [{ type: 'text' as const, text: String(result) }] }
            }) as Parameters<typeof server.registerTool>[2]
        )

        track(server, {
            apiKey: 'phc_test',
            posthogClient: makeStubPostHogClient(events),
            posthogOptions: { flushAt: 1, flushInterval: 0, host: 'https://test.posthog.com' },
            enableTracing: true,
            eventProperties: (request) => {
                const description = resolveExecInnerToolDescription(request)
                return description ? { $mcp_exec_tool_call_description: description } : {}
            },
        })

        const client = new Client({ name: 'test-client', version: '1.0.0' }, { capabilities: {} })
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        await Promise.all([client.connect(clientTransport), server.server.connect(serverTransport)])

        try {
            await client.request(
                {
                    method: 'tools/call',
                    params: { name: 'exec', arguments: { command: 'call execute-sql {}' } },
                },
                CallToolResultSchema
            )

            // Let the SDK flush.
            await new Promise((resolve) => setTimeout(resolve, 50))

            const toolCallEvent = events.find((e) => e.event === 'mcp_tool_call')
            expect(toolCallEvent, 'mcp_tool_call event should be captured').not.toBeUndefined()
            expect(toolCallEvent?.properties.$mcp_tool_name).toBe('exec')
            // The SDK property reports the *outer* tool's description (exec) — which is
            // exactly the uninformative case the dotcom property exists to fix.
            expect(toolCallEvent?.properties.$mcp_tool_description).toBe('exec tool')
            // The dotcom-side property carries the real inner-tool description.
            expect(toolCallEvent?.properties.$mcp_exec_tool_call_description).toBe(
                'Run a HogQL/SQL query against PostHog.'
            )
        } finally {
            await clientTransport.close?.()
            await serverTransport.close?.()
        }
    })

    it('omits $mcp_exec_tool_call_description for non-call verbs', async () => {
        const allTools = [makeTool({ name: 'execute-sql', description: 'Run a HogQL/SQL query against PostHog.' })]
        const events: CapturedEvent[] = []
        const server = new McpServer({ name: 'test-mcp', version: '1.0.0' })

        const resolveExecInnerToolDescription = (request: unknown): string | undefined => {
            const params = (request as { params?: { name?: unknown; arguments?: { command?: unknown } } })?.params
            if (params?.name !== 'exec' || typeof params.arguments?.command !== 'string') {
                return
            }
            const innerName = parseExecCallInnerToolName(params.arguments.command)
            return innerName ? allTools.find((t) => t.name === innerName)?.description : undefined
        }

        const execTool = createExecTool(allTools, mockContext, 'exec tool', 'command reference', undefined)
        server.registerTool(
            execTool.name,
            { title: execTool.title, description: execTool.description, inputSchema: execTool.schema.shape },
            (async (params: { command: string }) => {
                const result = await execTool.handler(mockContext, params)
                return { content: [{ type: 'text' as const, text: String(result) }] }
            }) as Parameters<typeof server.registerTool>[2]
        )

        track(server, {
            apiKey: 'phc_test',
            posthogClient: makeStubPostHogClient(events),
            posthogOptions: { flushAt: 1, flushInterval: 0, host: 'https://test.posthog.com' },
            enableTracing: true,
            eventProperties: (request) => {
                const description = resolveExecInnerToolDescription(request)
                return description ? { $mcp_exec_tool_call_description: description } : {}
            },
        })

        const client = new Client({ name: 'test-client', version: '1.0.0' }, { capabilities: {} })
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        await Promise.all([client.connect(clientTransport), server.server.connect(serverTransport)])

        try {
            // `info` verb references a tool but doesn't invoke it — should NOT
            // emit the description.
            await client.request(
                {
                    method: 'tools/call',
                    params: { name: 'exec', arguments: { command: 'info execute-sql' } },
                },
                CallToolResultSchema
            )

            await new Promise((resolve) => setTimeout(resolve, 50))

            const toolCallEvent = events.find((e) => e.event === 'mcp_tool_call')
            expect(toolCallEvent).not.toBeUndefined()
            expect(toolCallEvent?.properties).not.toHaveProperty('$mcp_exec_tool_call_description')
        } finally {
            await clientTransport.close?.()
            await serverTransport.close?.()
        }
    })
})
