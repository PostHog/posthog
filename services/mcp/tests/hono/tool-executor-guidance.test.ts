import { afterEach, beforeAll, describe, expect, it, type MockInstance, vi } from 'vitest'
import { z } from 'zod'

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn().mockRejectedValue(new Error('mocked')),
    filterValidEntries: vi.fn().mockReturnValue([]),
    loadManifestFromArchive: vi.fn().mockReturnValue({ resources: [] }),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/lib/posthog', async () => {
    const { PostHogMCP } = await import('@posthog/mcp-analytics')
    const client = new PostHogMCP('phc_test', { disabled: true, captureModel: true })
    return { getPostHogClient: () => client }
})

import { GuidanceEngine } from '@/hono/guidance/engine'
import { MCP_GUIDANCE_REPLAY_VISION_FLAG, MCP_GUIDANCE_SQL_SCHEMA_FLAG } from '@/hono/guidance/rules'
import { InstructionsBuilder } from '@/hono/instructions'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { getPostHogClient } from '@/lib/posthog'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

function makeTool(name: string, handler: (args: unknown) => unknown): any {
    return {
        name,
        title: name,
        description: `Synthetic ${name}`,
        scopes: [],
        annotations: { readOnlyHint: true },
        schema: z.object({ query: z.string().optional() }),
        handler: vi.fn(async (_context: unknown, args: unknown) => handler(args)),
    }
}

describe('ToolExecutor guidance notices', () => {
    let catalog: ToolCatalog

    beforeAll(async () => {
        catalog = new ToolCatalog()
        await catalog.warmup()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    type SqlResult = { isError?: boolean; content: { type: string; text?: string }[] }

    function setup(
        mode: string,
        sqlHandler: (args: unknown) => unknown,
        flag: string
    ): {
        callSql: (query: string) => Promise<SqlResult>
        capture: MockInstance<ReturnType<typeof getPostHogClient>['captureToolCall']>
    } {
        const sql = makeTool('execute-sql', sqlHandler)
        const vision = makeTool('vision-scanners-inline-scan', () => ({}))
        const schema = makeTool('read-data-schema', () => ({}))
        vi.spyOn(catalog, 'getToolByName').mockImplementation((name) => {
            const tool = [sql, vision, schema].find((t) => t.name === name)
            return tool
                ? { build: () => tool, meta: undefined, rawInputSchema: undefined, definition: undefined }
                : undefined
        })
        const executor = new ToolExecutor(
            catalog,
            new InstructionsBuilder(''),
            undefined,
            new GuidanceEngine(makeGuidanceRedis())
        )
        const state = makeToolExecutorState([sql, vision, schema], {
            useSingleExec: mode === 'exec',
            suppressAnalytics: false,
            toolFeatureFlags: { [flag]: true },
        })
        const capture = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const callSql = async (
            query: string
        ): Promise<{ isError?: boolean; content: { type: string; text?: string }[] }> => {
            const args = mode === 'exec' ? { command: `call execute-sql ${JSON.stringify({ query })}` } : { query }
            const result = await executor.handleToolCall(
                { name: mode === 'exec' ? 'exec' : 'execute-sql', arguments: args },
                state
            )
            await new Promise((resolve) => setImmediate(resolve))
            return result as any
        }
        return { callSql, capture }
    }

    it.each(['direct', 'exec'])('prepends the replay notice to the second replay query in %s mode', async (mode) => {
        const { callSql, capture } = setup(mode, () => ({ results: [] }), MCP_GUIDANCE_REPLAY_VISION_FLAG)
        const first = await callSql('select 1 from session_replay_events')
        const second = await callSql('select 2 from session_replay_events')

        expect(first.content[0]?.text).not.toContain('Replay Vision')
        expect(second.content[0]?.text).toContain('Replay Vision')
        expect(second.content).toHaveLength(first.content.length + 1)
        expect(capture.mock.calls.map(([call]) => call.properties?.mcp_guidance_rule)).toEqual([
            undefined,
            'replay-sql-to-vision',
        ])
    })

    it.each(['direct', 'exec'])('prepends the schema notice to the third failed query in %s mode', async (mode) => {
        const { callSql, capture } = setup(
            mode,
            () => {
                throw new Error('Unknown column')
            },
            MCP_GUIDANCE_SQL_SCHEMA_FLAG
        )
        await callSql('select a from b')
        await callSql('select a from b')
        const third = await callSql('select a from b')

        expect(third.isError).toBe(true)
        expect(third.content[0]?.text).toContain('read-data-schema')
        expect(capture.mock.calls.map(([call]) => call.properties?.mcp_guidance_rule)).toEqual([
            undefined,
            undefined,
            'sql-failures-to-schema',
        ])
    })
})
