import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createExecTool } from '@/tools/exec'
import { POSTHOG_META_KEY, type Context, type Tool, type ZodObjectAny } from '@/tools/types'

function makeMockTool(overrides: Partial<Tool<ZodObjectAny>> = {}): Tool<ZodObjectAny> {
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
        handler: async () => ({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] }),
        ...overrides,
    }
}

const mockContext = {} as Context

function createExec(tools: Tool<ZodObjectAny>[] = [makeMockTool()]): Tool<any> {
    return createExecTool(tools, mockContext, 'test description', 'test command reference')
}

describe('exec tool', () => {
    describe('call command', () => {
        it('returns TOON-formatted output by default', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call mock-tool {}' })
            // TOON format uses "key: value" style, not JSON
            expect(result).toContain('id: 1')
            expect(result).toContain('name: test')
            expect(result).not.toBe(JSON.stringify({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] }))
        })

        it('returns raw JSON with --json flag', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool {}' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns JSON for tool with responseFormat json even without flag', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { responseFormat: 'json' } } })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call mock-tool {}' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns JSON when both --json flag and responseFormat json are present', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { responseFormat: 'json' } } })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool {}' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('throws usage error for call --json with no tool name', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'call --json' })).rejects.toThrow(
                'Usage: call [--json] <tool_name> <json_input>'
            )
        })

        it('throws usage error for bare call', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'call' })).rejects.toThrow(
                'Usage: call [--json] <tool_name> <json_input>'
            )
        })

        it('does not treat --json in JSON body as the flag', async () => {
            const tool = makeMockTool({
                schema: z.object({ tag: z.string() }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, {
                command: 'call mock-tool {"tag": "--json"}',
            })
            // Without the flag, output is TOON-formatted
            expect(result).toContain('tag:')
        })
    })
})
