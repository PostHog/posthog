import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ExecCommandError } from '@/lib/errors'
import { buildGatewayTools } from '@/lib/gateway-tools'
import { createExecTool, type ExecCommandMeta } from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

const INPUT_SCHEMA = {
    type: 'object',
    properties: { title: { type: 'string', description: 'Issue title' } },
    required: ['title'],
}

function payload(
    overrides: Partial<Schemas.AvailableTool> = {},
    serverName = 'Linear',
    slug = 'linear'
): Schemas.AvailableToolsResponse {
    return {
        servers: [
            {
                installation_id: 'inst-1',
                name: serverName,
                slug,
                tools: [
                    {
                        name: 'create_issue',
                        description: 'Create an issue',
                        input_schema: INPUT_SCHEMA,
                        annotations: {},
                        approval_state: 'approved',
                        ...overrides,
                    } as Schemas.AvailableTool,
                ],
            },
        ],
    } as Schemas.AvailableToolsResponse
}

function mockContext(request = vi.fn()): Context {
    return { api: { request }, getDistinctId: async () => 'distinct-id' } as unknown as Context
}

function posthogTool(): Tool<ZodObjectAny> {
    return {
        name: 'feature-flag-create',
        title: 'Create feature flag',
        description: 'Create a PostHog feature flag',
        schema: z.object({ key: z.string() }),
        scopes: [],
        annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: false, readOnlyHint: false },
        handler: async () => ({ ok: true }),
    }
}

function createExec(
    gatewayTools: Tool<ZodObjectAny>[],
    provider = vi.fn(async () => gatewayTools)
): {
    exec: Tool<any>
    provider: ReturnType<typeof vi.fn>
} {
    const exec = createExecTool(
        [posthogTool()],
        mockContext(),
        'description',
        'command reference',
        undefined,
        undefined,
        [],
        { gatewayToolsProvider: provider }
    )
    return { exec, provider }
}

describe('gateway tools', () => {
    it('namespaces tool names by server slug and keeps the upstream JSON Schema', () => {
        const tools = buildGatewayTools(payload(), mockContext(), '1')

        expect(tools).toHaveLength(1)
        expect(tools[0]!.name).toBe('linear__create_issue')
        // PostHog's own names are kebab-case and never contain `__`, so the prefix is what
        // keeps a vendor tool from shadowing one of ours.
        expect(tools[0]!.name).toContain('__')
        expect(tools[0]!.rawInputSchema).toEqual(INPUT_SCHEMA)
    })

    it.each([
        ['omitted', {}, { destructiveHint: true, readOnlyHint: false, openWorldHint: true }],
        [
            'declared safe',
            { destructiveHint: false, readOnlyHint: true, openWorldHint: false },
            { destructiveHint: false, readOnlyHint: true, openWorldHint: false },
        ],
        ['declared destructive', { destructiveHint: true }, { destructiveHint: true, readOnlyHint: false }],
    ])('takes MCP spec defaults when annotations are %s', (_label, annotations, expected) => {
        // A server that declares nothing must not look safer than one that declares
        // itself destructive — the spec defaults destructiveHint to true.
        const tools = buildGatewayTools(payload({ annotations }), mockContext(), '1')

        expect(tools[0]!.annotations).toMatchObject(expected)
    })

    it('routes a call to the owning installation and returns the tool text', async () => {
        const request = vi.fn(async () => ({
            content: [{ type: 'text', text: 'ENG-1 created' }],
            is_error: false,
        }))
        const tools = buildGatewayTools(payload(), mockContext(request), '42')

        const result = await tools[0]!.handler(mockContext(), { title: 'Bug' })

        expect(result).toBe('ENG-1 created')
        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/mcp_server_installations/inst-1/call_tool/',
            body: { tool_name: 'create_issue', arguments: { title: 'Bug' } },
        })
    })

    it('surfaces a tool-reported failure as data so the agent can retry', async () => {
        const request = vi.fn(async () => ({
            content: [{ type: 'text', text: 'title is required' }],
            is_error: true,
        }))
        const tools = buildGatewayTools(payload(), mockContext(request), '1')

        await expect(tools[0]!.handler(mockContext(), {})).resolves.toEqual({
            error: 'title is required',
            server: 'Linear',
        })
    })

    it('turns a gateway refusal into an actionable error instead of a bare HTTP failure', async () => {
        // Without this the agent sees a 403 and retries forever, rather than learning it
        // needs a human to approve the tool in PostHog.
        const request = vi.fn(async () => {
            throw Object.assign(new Error('Forbidden'), {
                body: JSON.stringify({ detail: 'Tool needs approval in PostHog.', reason: 'needs_approval' }),
            })
        })
        const tools = buildGatewayTools(payload(), mockContext(request), '1')

        await expect(tools[0]!.handler(mockContext(), {})).rejects.toThrow(ExecCommandError)
        await expect(tools[0]!.handler(mockContext(), {})).rejects.toThrow('needs approval in PostHog')
    })

    it('rethrows an unrecognized API failure untouched', async () => {
        const boom = new Error('upstream exploded')
        const request = vi.fn(async () => {
            throw boom
        })
        const tools = buildGatewayTools(payload(), mockContext(request), '1')

        await expect(tools[0]!.handler(mockContext(), {})).rejects.toBe(boom)
    })

    it('finds and calls a gateway tool through exec', async () => {
        const handler = vi.fn(async () => 'called')
        const gatewayTool = { ...buildGatewayTools(payload(), mockContext(), '1')[0]!, handler }
        const { exec } = createExec([gatewayTool])

        const found = await exec.handler(mockContext(), { command: 'search create issue' })
        expect(found).toContain('linear__create_issue')

        await exec.handler(mockContext(), { command: 'call linear__create_issue {"title":"Bug"}' })
        expect(handler).toHaveBeenCalledWith(expect.anything(), { title: 'Bug' })
    })

    it('renders the upstream JSON Schema for info, not an empty derived one', async () => {
        const { exec } = createExec(buildGatewayTools(payload(), mockContext(), '1'))

        const info = (await exec.handler(mockContext(), {
            command: 'info --json linear__create_issue',
        })) as string

        expect(JSON.parse(info).inputSchema).toEqual(INPUT_SCHEMA)
    })

    it('summarizes connected tools in the listing rather than dumping them', async () => {
        const { exec } = createExec(buildGatewayTools(payload(), mockContext(), '1'))

        const listed = JSON.parse((await exec.handler(mockContext(), { command: 'tools' })) as string)

        expect(listed.tools).toEqual(['feature-flag-create'])
        expect(listed.connected_servers).toContain('linear')
    })

    it('does not touch the gateway for commands that need no tool roster', async () => {
        // The provider costs an API round trip, so `exec` must stay free for sessions
        // that never reach for a connected tool.
        const { exec, provider } = createExec(buildGatewayTools(payload(), mockContext(), '1'))

        await expect(exec.handler(mockContext(), { command: 'learn' })).rejects.toThrow()

        expect(provider).not.toHaveBeenCalled()
    })

    it('resolves the gateway once per command even when a lookup repeats', async () => {
        const { exec, provider } = createExec(buildGatewayTools(payload(), mockContext(), '1'))

        await exec.handler(mockContext(), { command: 'search issue' })

        expect(provider).toHaveBeenCalledTimes(1)
    })

    describe('command tracking', () => {
        function createTrackedExec(gatewayPayload: Schemas.AvailableToolsResponse = payload()): {
            exec: Tool<any>
            tracked: ExecCommandMeta[]
        } {
            const tracked: ExecCommandMeta[] = []
            const gatewayTools = buildGatewayTools(gatewayPayload, mockContext(), '1')
            const exec = createExecTool(
                [posthogTool()],
                mockContext(),
                'description',
                'command reference',
                undefined,
                undefined,
                [],
                {
                    gatewayToolsProvider: async () => gatewayTools,
                    trackCommand: (meta) => tracked.push(meta),
                }
            )
            return { exec, tracked }
        }

        // The zero-match row is the reason this tracking exists: a search that finds
        // nothing is the only record of a capability someone wanted and we lack. The
        // gateway count separates "we have this" from "a vendor has this".
        it.each([
            ['matches both a PostHog and a gateway tool', 'create issue', 2, 1],
            ['matches a PostHog tool only', 'feature flag', 1, 0],
            ['matches nothing', 'kubernetes', 0, 0],
        ])('reports a search that %s', async (_label, query, matchCount, gatewayMatchCount) => {
            const { exec, tracked } = createTrackedExec()

            await exec.handler(mockContext(), { command: `search ${query}` })

            expect(tracked.at(-1)).toEqual({
                exec_verb: 'search',
                exec_search_query: query,
                exec_search_match_count: matchCount,
                exec_search_gateway_match_count: gatewayMatchCount,
            })
        })

        it('counts every match, not just the page a truncated search returns', async () => {
            // A ranked search returns only its top page, so counting what was returned
            // would make a query matching far more tools look as narrow as one that
            // matched exactly a page — flattening the demand signal this exists to measure.
            const manyTools = {
                servers: [
                    {
                        installation_id: 'inst-1',
                        name: 'Linear',
                        slug: 'linear',
                        tools: Array.from({ length: 30 }, (_, i) => ({
                            name: `issue_action_${i}`,
                            description: 'Act on an issue',
                            input_schema: INPUT_SCHEMA,
                            annotations: {},
                            approval_state: 'approved',
                        })),
                    },
                ],
            } as Schemas.AvailableToolsResponse
            const { exec, tracked } = createTrackedExec(manyTools)

            const result = JSON.parse((await exec.handler(mockContext(), { command: 'search issue' })) as string)

            expect(result.truncated).toBe(true)
            expect(result.matches.length).toBeLessThan(30)
            expect(tracked.at(-1)).toEqual({
                exec_verb: 'search',
                exec_search_query: 'issue',
                exec_search_match_count: 30,
                exec_search_gateway_match_count: 30,
            })
        })

        it('reports the verb even when the command throws', async () => {
            const { exec, tracked } = createTrackedExec()

            await expect(exec.handler(mockContext(), { command: 'call nope {}' })).rejects.toThrow()

            expect(tracked).toEqual([{ exec_verb: 'call' }])
        })
    })
})
