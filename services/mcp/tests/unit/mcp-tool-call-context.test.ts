import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

vi.mock('agents/mcp', () => ({
    McpAgent: class {},
}))

vi.mock('@modelcontextprotocol/sdk/server/mcp.js', () => ({
    McpServer: class {},
}))

vi.mock('@modelcontextprotocol/ext-apps/server', () => ({
    RESOURCE_URI_META_KEY: 'resource-uri',
}))

vi.mock('@shared/guidelines.md', () => ({
    default: '',
}))

import { MCP } from '@/mcp'

describe('MCP tool call context', () => {
    it('accepts _mcp_context and strips it from handler params', async () => {
        let registeredHandler: ((params: Record<string, unknown>) => Promise<unknown>) | undefined
        let registeredInputSchema: Record<string, unknown> | undefined

        const mcp = Object.create(MCP.prototype) as MCP
        ;(mcp as any).toolCallContextEnabled = true
        ;(mcp as any).ctx = {
            waitUntil: vi.fn(),
        }
        ;(mcp as any).server = {
            registerTool: vi.fn((_name, options, handler) => {
                registeredInputSchema = options.inputSchema
                registeredHandler = handler
            }),
        }

        const handler = vi.fn().mockResolvedValue('ok')

        mcp.registerTool(
            {
                name: 'query-run',
                schema: z.object({ query: z.string() }),
            } as any,
            handler
        )

        expect(registeredInputSchema).toHaveProperty('_mcp_context')

        await registeredHandler?.({
            query: 'select 1',
            _mcp_context: 'checking activation counts for the user request',
        })

        expect(handler).toHaveBeenCalledWith({ query: 'select 1' })
    })
})
