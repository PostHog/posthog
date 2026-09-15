import { describe, expect, it, vi } from 'vitest'

import type { RequestContext } from '@/hono/request-context'
import { type ToolCallSessionRecord, advance, buildToolCallSessionState } from '@/hono/tool-call-session'

const fresh = (): ToolCallSessionRecord => ({ startedAt: 1_000, callCount: 0, schemaReadTools: [] })

describe('advance', () => {
    it('counts only call verbs', () => {
        let record = fresh()
        for (const verb of ['tools', 'search', 'info', 'schema']) {
            record = advance(record, { verb, targetTool: 'experiment-get', schemaRequiresRead: true })
        }
        expect(record.callCount).toBe(0)

        record = advance(record, { verb: 'call', targetTool: 'experiment-get', schemaRequiresRead: true })
        expect(record.callCount).toBe(1)
    })

    it('remembers each tool whose schema was read, once, newest last', () => {
        let record = fresh()
        record = advance(record, { verb: 'info', targetTool: 'experiment-get', schemaRequiresRead: true })
        record = advance(record, { verb: 'schema', targetTool: 'experiment-update', schemaRequiresRead: true })
        record = advance(record, { verb: 'info', targetTool: 'experiment-get', schemaRequiresRead: true })

        expect(record.schemaReadTools).toEqual(['experiment-get', 'experiment-update'])
    })

    it('ignores a schema read that named no tool', () => {
        const record = advance(fresh(), { verb: 'info', targetTool: undefined, schemaRequiresRead: true })
        expect(record.schemaReadTools).toEqual([])
    })

    it('bounds the schema-read list, forgetting the oldest', () => {
        let record = fresh()
        for (let i = 0; i < 120; i++) {
            record = advance(record, { verb: 'info', targetTool: `tool-${i}`, schemaRequiresRead: true })
        }
        expect(record.schemaReadTools).toHaveLength(100)
        expect(record.schemaReadTools[0]).toBe('tool-20')
    })
})

describe('buildToolCallSessionState', () => {
    function memoryCache(): { get: ReturnType<typeof vi.fn>; set: ReturnType<typeof vi.fn> } {
        const store = new Map<string, unknown>()
        return {
            get: vi.fn(async (key: string) => store.get(key)),
            set: vi.fn(async (key: string, value: unknown) => {
                store.set(key, value)
            }),
        }
    }

    function reqCtxWith(cache: unknown): RequestContext {
        return { getSessionCache: vi.fn(() => cache) } as unknown as RequestContext
    }

    it('is absent without an MCP session id', () => {
        expect(buildToolCallSessionState(reqCtxWith(memoryCache()), undefined)).toBeUndefined()
    })

    it('links an info read to the call that follows it, across requests', async () => {
        vi.useFakeTimers()
        try {
            vi.setSystemTime(10_000)
            const cache = memoryCache()

            // Each request builds its own state, as the executor does.
            const first = await buildToolCallSessionState(reqCtxWith(cache), 'mcp-1')!.observe({
                verb: 'info',
                targetTool: 'experiment-get',
                schemaRequiresRead: true,
            })
            expect(first).toEqual({ $mcp_session_tool_call_index: 0, $mcp_session_age_ms: 0 })

            vi.setSystemTime(12_500)
            const second = await buildToolCallSessionState(reqCtxWith(cache), 'mcp-1')!.observe({
                verb: 'call',
                targetTool: 'experiment-get',
                schemaRequiresRead: true,
            })
            expect(second).toEqual({
                $mcp_session_tool_call_index: 1,
                $mcp_session_age_ms: 2_500,
                $mcp_schema_read_before_call: true,
            })

            const third = await buildToolCallSessionState(reqCtxWith(cache), 'mcp-1')!.observe({
                verb: 'call',
                targetTool: 'experiment-update',
                schemaRequiresRead: true,
            })
            expect(third).toMatchObject({ $mcp_session_tool_call_index: 2, $mcp_schema_read_before_call: false })
        } finally {
            vi.useRealTimers()
        }
    })

    it('omits the schema-read flag when the schema was already in the tool listing', async () => {
        const properties = await buildToolCallSessionState(reqCtxWith(memoryCache()), 'mcp-1')!.observe({
            verb: 'call',
            targetTool: 'experiment-get',
            schemaRequiresRead: false,
        })

        expect(properties).not.toHaveProperty('$mcp_schema_read_before_call')
        expect(properties).toMatchObject({ $mcp_session_tool_call_index: 1 })
    })

    it('surfaces a cache failure to the caller rather than swallowing it', async () => {
        const failing = { get: vi.fn().mockRejectedValue(new Error('redis down')), set: vi.fn() }

        await expect(
            buildToolCallSessionState(reqCtxWith(failing), 'mcp-1')!.observe({
                verb: 'call',
                targetTool: 'experiment-get',
                schemaRequiresRead: true,
            })
        ).rejects.toThrow('redis down')
    })
})
