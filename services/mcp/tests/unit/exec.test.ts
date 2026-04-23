import guidelines from '@shared/guidelines.md'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
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
            const commandReference = buildInstructionsV2(CLI_PROXY_COMMAND, guidelines, undefined, undefined, toolInfos)
            const execTool = createExecTool(v2Tools, context, CLI_PROXY_TOOL, commandReference)

            expect(execTool.description.length).toBeLessThanOrEqual(2048)
        })

        // Snapshots the full exec tool definition built from the real v2 tool set:
        // description (CLI_PROXY_TOOL), annotations, and input schema including the
        // `command` field description — which embeds the generated `tool_domains`
        // block. Because `buildToolDomainsBlock` relies on tool-name conventions
        // (CRUD suffixes, prefix actions, plural collapsing), this snapshot is the
        // canary for any drift in naming or in the domain-extraction logic.
        it('matches the full exec tool schema', async () => {
            const context = createSnapshotContext()
            const v2Tools = [...(await getToolsFromContext(context, { version: 2 }))].sort((a, b) =>
                a.name.localeCompare(b.name)
            )
            const toolInfos = v2Tools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name, 2).category,
            }))
            const commandReference = buildInstructionsV2(CLI_PROXY_COMMAND, guidelines, undefined, undefined, toolInfos)
            const execTool = createExecTool(v2Tools, context, CLI_PROXY_TOOL, commandReference)

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
            await expect(`${JSON.stringify(snapshot, null, 4)}\n`).toMatchFileSnapshot(snapshotPath)
        })
    })
})
