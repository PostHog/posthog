import guidelines from '@shared/guidelines.md'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { format } from 'oxfmt'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { buildInstructionsV2 } from '@/lib/instructions'
import { SessionManager } from '@/lib/SessionManager'
import CLI_PROXY_COMMAND from '@/templates/cli-proxy-command.md'
import CLI_PROXY_TOOL from '@/templates/cli-proxy-tool.md'
import { getToolsFromContext } from '@/tools'
import { createExecTool } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
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

const mockContext = {
    getDistinctId: async () => 'test-distinct-id',
} as unknown as Context

function createExec(tools: Tool<ZodObjectAny>[] = [makeMockTool()], mcpConsumer?: string): Tool<any> {
    return createExecTool(tools, mockContext, 'test description', 'test command reference', mcpConsumer)
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

        it('returns JSON for tool with outputFormat json even without flag', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { outputFormat: 'json' } } })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call mock-tool {}' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns JSON when both --json flag and outputFormat json are present', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { outputFormat: 'json' } } })
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

        it('propagates _meta.ui.resourceUri and structuredContent when the inner tool has a UI app and consumer is posthog-code', async () => {
            const tool = makeMockTool({
                _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
            })
            const exec = createExec([tool], 'posthog-code')
            const result = (await exec.handler(mockContext, { command: 'call mock-tool {}' })) as {
                content: { type: string; text: string }[]
                structuredContent: { id: number; name: string; _analytics: { distinctId: string; toolName: string } }
                _meta: { ui: { resourceUri: string }; [key: string]: unknown }
                __execBuiltPayload?: true
            }

            // Text content still includes the TOON-formatted result for model context
            expect(result.content[0]!.text).toContain('id: 1')
            // structuredContent carries the raw object plus analytics for the UI app
            expect(result.structuredContent.id).toBe(1)
            expect(result.structuredContent._analytics).toEqual({
                distinctId: 'test-distinct-id',
                toolName: 'mock-tool',
            })
            // _meta on the response exposes the UI resource URI to clients that
            // only see the `exec` tool registered (single-exec mode). Both the
            // new nested key and the legacy flat key are emitted for
            // compatibility with older MCP clients.
            expect(result._meta.ui.resourceUri).toBe('ui://posthog/mock-app.html')
            expect(result._meta['ui/resourceUri']).toBe('ui://posthog/mock-app.html')
            // The nominal brand is what `MCP.registerTool` uses to pass the payload
            // through unchanged; without it the outer wrapper would re-run
            // buildToolResultPayload and object-rest-destructure the content.
            expect(result.__execBuiltPayload).toBe(true)
        })

        it.each([[undefined], ['cline'], ['claude-code'], ['slack'], ['posthog_code']])(
            'returns plain text (no UI payload) when consumer is %s even if the inner tool has a UI app',
            async (consumer) => {
                const tool = makeMockTool({
                    _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
                })
                const exec = createExec([tool], consumer)
                const result = await exec.handler(mockContext, { command: 'call mock-tool {}' })
                expect(typeof result).toBe('string')
            }
        )

        it('does not attach UI meta or structuredContent for tools without a UI app', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call mock-tool {}' })
            // Plain text fallback — no CallToolResult shape leaks out
            expect(typeof result).toBe('string')
        })
    })

    describe('schema snapshot', () => {
        function createSnapshotContext(): Context {
            return {
                api: {} as any,
                cache: {} as any,
                env: {
                    INKEEP_API_KEY: 'test-key',
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                    POSTHOG_UI_APPS_TOKEN: undefined,
                },
                stateManager: {
                    getApiKey: async () => ({ scopes: ['*'] }),
                    getAiConsentGiven: async () => true,
                } as any,
                sessionManager: new SessionManager({} as any),
                getDistinctId: async () => 'test-distinct-id',
            }
        }

        // Claude Code truncates tool descriptions after 2048 characters, so the
        // exec tool's description must fit within that budget or clients will
        // silently drop the tail of the instructions.
        it('keeps the tool description within 2048 characters', async () => {
            const context = createSnapshotContext()
            const v2Tools = await getToolsFromContext(context, { version: 2 })
            const toolInfos = v2Tools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name, 2).category,
            }))
            const queryToolInfos = v2Tools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name, 2)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    }
                })
            const commandReference = buildInstructionsV2(
                CLI_PROXY_COMMAND,
                guidelines,
                undefined,
                undefined,
                toolInfos,
                queryToolInfos
            )
            const execTool = createExecTool(v2Tools, context, CLI_PROXY_TOOL, commandReference, undefined)

            expect(execTool.description.length).toBeLessThanOrEqual(2048)
        })

        // Snapshots the full exec tool definition built from the real v2 tool set:
        // description (CLI_PROXY_TOOL), annotations, and input schema including the
        // `command` field description — which embeds the generated `tool_domains`
        // block. Because `buildToolDomainsBlock` relies on tool-name conventions
        // (CRUD suffixes, prefix actions, plural collapsing), this snapshot is the
        // canary for any drift in naming or in the domain-extraction logic.
        //
        // Snapshots the Codex (`supportsInstructions: false`) wiring, where every
        // placeholder is filled. That's the only path where `{tool_domains}` and
        // `{query_tools}` actually appear in the `command` parameter description,
        // so the snapshot has to follow it to keep catching drift in those blocks.
        it('matches the full exec tool schema', async () => {
            const context = createSnapshotContext()
            const v2Tools = [...(await getToolsFromContext(context, { version: 2 }))].sort((a, b) =>
                a.name.localeCompare(b.name)
            )
            const toolInfos = v2Tools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name, 2).category,
            }))
            const queryToolInfos = v2Tools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name, 2)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    }
                })
            const commandReference = buildInstructionsV2(
                CLI_PROXY_COMMAND,
                guidelines,
                undefined,
                undefined,
                toolInfos,
                queryToolInfos
            )
            const execTool = createExecTool(v2Tools, context, CLI_PROXY_TOOL, commandReference, undefined)

            const snapshot = {
                name: execTool.name,
                title: execTool.title,
                description: execTool.description,
                annotations: execTool.annotations,
                scopes: execTool.scopes,
                inputSchema: z.toJSONSchema(execTool.schema, { io: 'input', reused: 'inline' }),
            }

            const __dirname = path.dirname(fileURLToPath(import.meta.url))
            const snapshotPath = path.resolve(__dirname, '__snapshots__', 'exec-tool.json')
            // Format via oxfmt so the snapshot matches repo-wide formatting rules
            // (lint-staged reformats *.json and would otherwise flip this file on save).
            const content = `${JSON.stringify(snapshot, null, 4)}\n`
            const result = await format(snapshotPath, content, { tabWidth: 4, printWidth: 120 })
            if (result.errors.length > 0) {
                throw new Error(
                    `Failed formatting snapshot: ${result.errors.map((e) => e.message ?? 'unknown').join('; ')}`
                )
            }
            await expect(result.code).toMatchFileSnapshot(snapshotPath)
        })
    })
})
