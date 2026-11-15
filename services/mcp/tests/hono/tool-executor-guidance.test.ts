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
import {
    MCP_GUIDANCE_REPLAY_VISION_FLAG,
    MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG,
    MCP_GUIDANCE_SQL_SCHEMA_FLAG,
    type GuidanceRule,
} from '@/hono/guidance/rules'
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
        flag: string,
        callFlags = ''
    ): {
        callSql: (query: string) => Promise<SqlResult>
        capture: MockInstance<ReturnType<typeof getPostHogClient>['captureToolCall']>
    } {
        const sql = makeTool('execute-sql', sqlHandler)
        const visionTools = [
            'vision-scanners-inline-scan',
            'vision-requests-create',
            'vision-requests-get',
            'vision-observations-search',
        ].map((name) => makeTool(name, () => ({})))
        const schema = makeTool('read-data-schema', () => ({}))
        const tools = [sql, ...visionTools, schema]
        vi.spyOn(catalog, 'getToolByName').mockImplementation((name) => {
            const tool = tools.find((t) => t.name === name)
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
        const state = makeToolExecutorState(tools, {
            useSingleExec: mode === 'exec',
            suppressAnalytics: false,
            aiConsentGiven: true,
            toolFeatureFlags: { [flag]: true },
        })
        const capture = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const callSql = async (
            query: string
        ): Promise<{ isError?: boolean; content: { type: string; text?: string }[] }> => {
            const args =
                mode === 'exec' ? { command: `call ${callFlags}execute-sql ${JSON.stringify({ query })}` } : { query }
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
        expect(capture.mock.calls[1]?.[0].properties?.mcp_guidance_outcome).toBe('shown')
    })

    it('keeps the JSON result as the first block when guidance fires on a --json call', async () => {
        const { callSql } = setup('exec', () => ({ results: [[1]] }), MCP_GUIDANCE_REPLAY_VISION_FLAG, '--json ')
        await callSql('select 1 from session_replay_events')
        const second = await callSql('select 2 from session_replay_events')

        expect(() => JSON.parse(second.content[0]?.text ?? '')).not.toThrow()
        expect(second.content[1]?.text).toContain('Replay Vision')
    })

    it('stamps flag_off on the event and leaves the result alone when the flag is off', async () => {
        const { callSql, capture } = setup('direct', () => ({ results: [] }), 'some-other-flag')
        const first = await callSql('select 1 from session_replay_events')
        const second = await callSql('select 2 from session_replay_events')

        expect(second.content).toEqual(first.content)
        expect(capture.mock.calls[1]?.[0].properties).toMatchObject({
            mcp_guidance_rule: 'replay-sql-to-vision',
            mcp_guidance_outcome: 'flag_off',
        })
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

    it.each(['direct', 'exec'])('passes an empty list result to guidance in %s mode', async (mode) => {
        const issuesList = makeTool('query-error-tracking-issues-list', () => ({ results: [] }))
        vi.spyOn(catalog, 'getToolByName').mockImplementation((name) =>
            name === issuesList.name
                ? { build: () => issuesList, meta: undefined, rawInputSchema: undefined, definition: undefined }
                : undefined
        )
        const emptyRule: GuidanceRule = {
            id: 'empty-result-rule',
            flag: 'mcp-guidance-empty-result',
            trigger: { tool: issuesList.name, resultEmpty: true, outcome: 'success', presets: ['user'] },
            threshold: 1,
            maxPerSession: 1,
            suppressIfCalled: [],
            requiresTool: [issuesList.name],
            text: 'The result is empty.',
        }
        const executor = new ToolExecutor(
            catalog,
            new InstructionsBuilder(''),
            undefined,
            new GuidanceEngine(makeGuidanceRedis(), [emptyRule])
        )
        const state = makeToolExecutorState([issuesList], {
            useSingleExec: mode === 'exec',
            suppressAnalytics: false,
            toolFeatureFlags: { [emptyRule.flag]: true },
        })

        const result = (await executor.handleToolCall(
            mode === 'exec'
                ? { name: 'exec', arguments: { command: `call ${issuesList.name} {}` } }
                : { name: issuesList.name, arguments: {} },
            state
        )) as SqlResult

        expect(result.content[0]?.text).toContain('The result is empty.')
    })

    it.each([
        ['query-error-tracking-issue', 'direct', false, false],
        ['query-error-tracking-issue', 'exec', false, false],
        ['query-error-tracking-issue', 'exec', true, false],
        ['query-error-tracking-issue', 'direct', false, true],
        ['query-error-tracking-issue', 'exec', true, true],
        ['query-error-tracking-issues-list', 'direct', false, false],
        ['query-error-tracking-issues-list', 'exec', false, false],
        ['query-error-tracking-issues-list', 'exec', true, false],
        ['query-error-tracking-issues-list', 'direct', false, true],
        ['query-error-tracking-issues-list', 'exec', true, true],
    ] as const)(
        'preserves %s results in %s with activation guidance (json=%s, readiness failure=%s)',
        async (toolName, mode, json, fails) => {
            const issueId = '019a0000-0000-7000-8000-000000000001'
            const isList = toolName === 'query-error-tracking-issues-list'
            const args = isList ? {} : { issueId }
            const result = isList ? [{ id: issueId }] : { id: issueId }
            const issue = {
                ...makeTool(toolName, () => result),
                schema: isList ? z.object({}) : z.object({ issueId: z.uuid() }),
            }
            const tools = [
                issue,
                ...[
                    'self-driving-status-get',
                    'inbox-reports-list',
                    'inbox-reports-retrieve',
                    'inbox-report-artefacts-list',
                ].map((name) => makeTool(name, () => ({}))),
            ]
            vi.spyOn(catalog, 'getToolByName').mockImplementation((name) => {
                const tool = tools.find((candidate) => candidate.name === name)
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
            const state = makeToolExecutorState(tools, {
                useSingleExec: mode === 'exec',
                suppressAnalytics: false,
                aiConsentGiven: true,
                toolFeatureFlags: { [MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG]: true },
            })
            const readiness = vi.fn().mockResolvedValue({ completed_at: null, draft: null })
            if (fails) {
                vi.spyOn(console, 'warn').mockImplementation(() => {})
                readiness.mockRejectedValue(new Error('readiness unavailable'))
            }
            state.context.api.request = readiness
            state.context.api.getProjectBaseUrl = vi.fn().mockReturnValue('https://example.com/project/2')
            state.context.stateManager.getProjectId = vi.fn().mockResolvedValue('2')
            const capture = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
            const params = {
                name: mode === 'exec' ? 'exec' : issue.name,
                arguments:
                    mode === 'exec'
                        ? { command: `call ${json ? '--json ' : ''}${issue.name} ${JSON.stringify(args)}` }
                        : args,
            }
            const first = (await executor.handleToolCall(params, state)) as SqlResult
            const second = (await executor.handleToolCall(params, state)) as SqlResult
            await new Promise((resolve) => setImmediate(resolve))

            if (fails) {
                expect(first.isError).not.toBe(true)
                expect(first.content).toEqual(second.content)
                expect(
                    first.content.some((item) => item.text?.includes('[Connect GitHub and activate Self-driving]'))
                ).toBe(false)
                expect(capture.mock.calls[0]?.[0].properties?.mcp_guidance_rule).toBeUndefined()
                return
            }
            expect(first.content[json ? 1 : 0]?.text).toContain('[Connect GitHub and activate Self-driving]')
            expect(first.content).toHaveLength(second.content.length + 1)
            expect(first.content[json ? 0 : 1]).toEqual(second.content[0])
            if (json) {
                expect(JSON.parse(first.content[0]?.text ?? '')).toEqual(result)
            }
            expect(readiness).toHaveBeenCalledTimes(1)
            expect(capture.mock.calls[0]?.[0].properties).toMatchObject({
                mcp_guidance_rule: 'error-tracking-sd-activation',
                mcp_guidance_outcome: 'shown',
            })
            expect(capture.mock.calls[1]?.[0].properties?.mcp_guidance_rule).toBeUndefined()
        }
    )
})
