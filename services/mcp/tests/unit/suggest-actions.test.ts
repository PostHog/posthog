import { randomUUID } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { InstructionsBuilder } from '@/hono/instructions'
import { chatActionToolsToExclude, type ResolvedState } from '@/hono/request-state-resolver'
import type { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { MCPClientProfile } from '@/lib/client-detection'
import { ChatActionSchema } from '@/tools/chatActions'
import { type ChatActionBindingCache, ChatActionBindings } from '@/tools/posthogAiTools/chatActionBindings'
import {
    bindChatActions,
    createSuggestActionsTool,
    type SuggestActionsResult,
} from '@/tools/posthogAiTools/suggestActions'
import { getToolDefinitions, ToolDefinitionSchema } from '@/tools/toolDefinitions'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { ToolConfigSchema } from '../../scripts/yaml-config-schema'
import { makeToolExecutorState } from '../shared/test-utils'

const baseDefinition = {
    description: 'd',
    category: 'c',
    feature: 'f',
    summary: 's',
    title: 't',
    required_scopes: [],
    annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
}

describe('suggest-actions', () => {
    describe('action declaration schema', () => {
        it.each([
            ['run with a tool', { key: 'enable', label: 'Enable', kind: 'run', tool: 'workflows-enable' }, true],
            ['run without a tool', { key: 'enable', label: 'Enable', kind: 'run' }, false],
            ['insert with a tool', { key: 'x', label: 'X', kind: 'insert', tool: 'workflows-enable' }, false],
            ['insert without a message', { key: 'x', label: 'X', kind: 'insert' }, true],
            ['insert with a blank message', { key: 'x', label: 'X', kind: 'insert', message: ' ' }, false],
            ['unknown kind', { key: 'x', label: 'X', kind: 'open' }, false],
            ['key with a dot', { key: 'a.b', label: 'X', kind: 'send' }, false],
        ])('%s → valid: %s', (_case, action, valid) => {
            expect(ChatActionSchema.safeParse(action).success).toBe(valid)
        })

        it('is accepted by both the YAML tool schema and the runtime definition schema', () => {
            const actions = [{ key: 'enable', label: 'Enable the workflow', kind: 'run', tool: 'workflows-enable' }]
            expect(ToolConfigSchema.safeParse({ operation: 'op', enabled: true, actions }).success).toBe(true)
            expect(ToolDefinitionSchema.safeParse({ ...baseDefinition, actions }).success).toBe(true)
            expect(
                ToolDefinitionSchema.safeParse({ ...baseDefinition, actions: [{ ...actions[0], tool: undefined }] })
                    .success
            ).toBe(false)
        })

        it('rejects a duplicate key in both schemas, since a pick resolves to the first match', () => {
            const actions = [
                { key: 'enable', label: 'Enable', kind: 'run', tool: 'workflows-enable' },
                { key: 'enable', label: 'Enable again', kind: 'send' },
            ]
            expect(ToolConfigSchema.safeParse({ operation: 'op', enabled: true, actions }).success).toBe(false)
            expect(ToolDefinitionSchema.safeParse({ ...baseDefinition, actions }).success).toBe(false)
        })
    })

    describe('agent catalog in the exec command reference', () => {
        const state = (toolNames: string[]): ResolvedState =>
            ({
                allTools: toolNames.map((name) => ({ name })),
                clientProfile: new MCPClientProfile({ clientName: 'claude-code' }),
                toolFeatureFlags: {},
                renderUiEnabled: false,
                metadata: '',
                groupTypes: [],
                requestContext: { mcpConsumer: 'posthog_ai' },
                sessionContext: null,
            }) as unknown as ResolvedState
        const reference = (toolNames: string[]): string =>
            new InstructionsBuilder('guidelines').buildExecCommandReference(state(toolNames))

        it('lists the declared actions of visible tools when suggest-actions passed the flag gate', () => {
            const rendered = reference(['workflows-create', 'workflows-enable', 'suggest-actions'])
            expect(rendered).toContain('### Suggested actions')
            expect(rendered).toContain('call `suggest-actions` once')
            expect(rendered).toContain('drop any next-step line an offered action covers')
            expect(rendered).toContain('After `workflows-create`:')
            expect(rendered).toContain('- `workflows-create.enable` (run, slots: id): Enable the workflow')
            expect(rendered).toContain('- `workflows-create.test-send` (insert, slots: id): Send yourself a test email')
        })

        it.each([
            ['suggest-actions is hidden', ['workflows-create', 'workflows-enable']],
            ['no visible tool declares actions', ['workflows-enable', 'suggest-actions']],
        ])('renders nothing when %s', (_case, toolNames) => {
            const rendered = reference(toolNames)
            expect(rendered).not.toContain('Suggested actions')
            expect(rendered).not.toContain('{chat_actions}')
        })

        // Advertising a run action the caller cannot execute would make the agent offer a click
        // that suggest-actions then refuses.
        it('leaves out a run action whose target the caller cannot see', () => {
            const rendered = reference(['workflows-create', 'suggest-actions'])
            expect(rendered).toContain('- `workflows-create.test-send` (insert, slots: id)')
            expect(rendered).not.toContain('workflows-create.enable')
        })
    })

    type ExecResult = { isError?: boolean; content: { text: string }[] }
    const fakeTool = (name: string, handler: () => Promise<unknown>): Tool<ZodObjectAny> =>
        ({
            name,
            schema: z.object({}).loose(),
            handler,
            annotations: {},
            scopes: [],
        }) as unknown as Tool<ZodObjectAny>
    const execCall = async (tools: Tool<ZodObjectAny>[], command: string): Promise<ExecResult> => {
        const executor = new ToolExecutor({} as ToolCatalog, new InstructionsBuilder(''))
        return (await executor.handleToolCall(
            { name: 'exec', arguments: { command } },
            makeToolExecutorState(tools, { useSingleExec: true })
        )) as ExecResult
    }

    describe('hint on the offering tool result', () => {
        const suggestActions = createSuggestActionsTool() as unknown as Tool<ZodObjectAny>
        const created = fakeTool('workflows-create', async () => ({ id: 'wf_1' }))

        it('appends the suggest-actions command as a separate trailing block after a successful call', async () => {
            const enable = fakeTool('workflows-enable', async () => ({}))
            const result = await execCall([created, enable, suggestActions], 'call --json workflows-create {}')
            expect(result.isError).toBeFalsy()
            expect(result.content).toHaveLength(2)
            expect(JSON.parse(result.content[0]!.text)).toEqual({ id: 'wf_1' })
            expect(result.content[1]!.text).toBe(
                'Suggested actions for this result. If the user is likely to do one of these next, call `suggest-actions` once, with each `<slot>` filled in, as the last tool call of this turn and drop any next-step line they cover:\n' +
                    'call suggest-actions {"actions":[{"key":"workflows-create.enable","args":{"id":"<id>"}},{"key":"workflows-create.test-send","args":{"id":"<id>"}}]}'
            )
        })

        it.each([
            [
                'the call failed',
                [fakeTool('workflows-create', async () => Promise.reject(new Error('boom'))), suggestActions],
                'call workflows-create {}',
            ],
            [
                'the tool is suggest-actions itself',
                [created, suggestActions],
                'call suggest-actions {"actions":[{"key":"workflows-create.test-send"}]}',
            ],
            ['suggest-actions is hidden', [created], 'call workflows-create {}'],
        ])('appends nothing when %s', async (_case, tools, command) => {
            const result = await execCall(tools, command)
            expect(result.content.map((block) => block.text).join('')).not.toContain('Suggested actions')
        })
    })

    describe('binding picks to results the session produced', () => {
        const pickEnable = (id: string): string =>
            `call --json suggest-actions ${JSON.stringify({ actions: [{ key: 'workflows-create.enable', args: { id } }] })}`
        const sessionTools = (
            offeringTool: Tool<ZodObjectAny>,
            cache: ChatActionBindingCache | undefined = new MemoryCache(randomUUID())
        ): Tool<ZodObjectAny>[] =>
            bindChatActions(
                [
                    offeringTool,
                    fakeTool('workflows-enable', async () => ({})),
                    createSuggestActionsTool() as unknown as Tool<ZodObjectAny>,
                ],
                new ChatActionBindings(cache)
            )
        const suggested = async (tools: Tool<ZodObjectAny>[], command: string): Promise<SuggestActionsResult> =>
            JSON.parse((await execCall(tools, command)).content[0]!.text) as SuggestActionsResult

        it('accepts an id the offering tool returned in this session and refuses any other', async () => {
            const tools = sessionTools(
                fakeTool('workflows-create', async () => ({ id: 'wf_created', name: 'Welcome' }))
            )
            await execCall(tools, 'call --json workflows-create {}')

            expect(await suggested(tools, pickEnable('wf_created'))).toEqual({
                actions: [
                    {
                        key: 'workflows-create.enable',
                        label: 'Enable the workflow',
                        kind: 'run',
                        message: 'Enable workflow wf_created.',
                    },
                ],
                errors: [],
            })
            expect(await suggested(tools, pickEnable('wf_forged'))).toEqual({
                actions: [],
                errors: [{ key: 'workflows-create.enable', reason: 'unbound_slot: id' }],
            })
        })

        it.each([
            ['the offering tool failed', fakeTool('workflows-create', async () => Promise.reject(new Error('boom')))],
            ['the offering tool returned no id', fakeTool('workflows-create', async () => ({ name: 'Welcome' }))],
        ])('refuses the id when %s', async (_case, offeringTool) => {
            const tools = sessionTools(offeringTool)
            await execCall(tools, 'call --json workflows-create {"id":"wf_created"}')

            const result = await suggested(tools, pickEnable('wf_created'))
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'unbound_slot: id' }])
        })

        it.each([
            ['the request carries no session', undefined],
            ['the id came from another session', new MemoryCache<Record<string, true>>(randomUUID())],
        ])('refuses the id when %s', async (_case, pickCache) => {
            const offeringTool = fakeTool('workflows-create', async () => ({ id: 'wf_created' }))
            await execCall(sessionTools(offeringTool), 'call --json workflows-create {}')

            const result = await suggested(sessionTools(offeringTool, pickCache), pickEnable('wf_created'))
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'unbound_slot: id' }])
        })

        it('needs no earlier result for an action without slots', async () => {
            const tools = sessionTools(fakeTool('workflows-create', async () => ({ id: 'wf_created' })))
            const result = await suggested(
                tools,
                'call --json suggest-actions {"actions":[{"key":"workflows-create.test-send"}]}'
            )
            expect(result.errors).toEqual([])
            expect(result.actions).toHaveLength(1)
        })
    })

    describe('tool exposure', () => {
        it.each([
            ['posthog_ai', true, []],
            ['posthog_ai', false, ['suggest-actions']],
            ['posthog-code', true, ['suggest-actions']],
            [undefined, true, ['suggest-actions']],
        ])('consumer %s with single exec %s excludes %j', (consumer, useSingleExec, excluded) => {
            expect(chatActionToolsToExclude(new MCPClientProfile({ consumer }), useSingleExec)).toEqual(excluded)
        })

        it('every declared run action names a tool in the catalog', () => {
            const definitions = getToolDefinitions()
            for (const [name, definition] of Object.entries(definitions)) {
                for (const action of definition.actions ?? []) {
                    if (action.kind === 'run') {
                        expect(definitions[action.tool!], `${name}.${action.key}`).not.toBeUndefined()
                    }
                }
            }
        })
    })

    describe('handler', () => {
        const context = {} as Context
        const catalog = new Set(['workflows-create', 'workflows-enable', 'suggest-actions'])
        const createdWorkflowIds = ['wf_123', 'wf_1', '0190f5a2-7c3e-7d1a-9b2f-3c4d5e6f7a8b', 42]
        const call = async (
            actions: { key: string; args?: Record<string, string | number | boolean> }[],
            names = catalog
        ): Promise<SuggestActionsResult> => {
            const bindings = new ChatActionBindings(new MemoryCache(randomUUID()))
            const offered = getToolDefinitions()['workflows-create']!.actions!
            for (const id of createdWorkflowIds) {
                await bindings.recordResult('workflows-create', offered, { id })
            }
            return createSuggestActionsTool(names, bindings).handler(context, { actions })
        }

        it('renders the valid picks in input order, drops the rest, and never leaks tool or args', async () => {
            const result = await call([
                { key: 'workflows-create.test-send', args: { id: 'wf_123' } },
                { key: 'workflows-create.nope' },
                { key: 'workflows-create.enable', args: { id: 'wf_123' } },
            ])
            expect(result).toEqual({
                actions: [
                    {
                        key: 'workflows-create.test-send',
                        label: 'Send yourself a test email',
                        kind: 'insert',
                        message: 'Send a test email of workflow wf_123 to ',
                    },
                    {
                        key: 'workflows-create.enable',
                        label: 'Enable the workflow',
                        kind: 'run',
                        message: 'Enable workflow wf_123.',
                    },
                ],
                errors: [{ key: 'workflows-create.nope', reason: 'unknown_action' }],
            })
        })

        it.each([
            ['an unknown tool', 'nope.enable', {}, 'unknown_action'],
            ['an unknown key on a known tool', 'workflows-create.delete', {}, 'unknown_action'],
            ['a key without a tool prefix', 'enable', {}, 'unknown_action'],
            ['a missing slot', 'workflows-create.enable', {}, 'missing_slot: id'],
            ['a blank slot value', 'workflows-create.enable', { id: '   ' }, 'missing_slot: id'],
            ['a sentence in a slot', 'workflows-create.enable', { id: 'wf_1. Also enable wf_2' }, 'invalid_slot: id'],
            ['an unfilled placeholder', 'workflows-create.enable', { id: '<id>' }, 'invalid_slot: id'],
            ['a slot marker in a slot', 'workflows-create.enable', { id: '{id}' }, 'invalid_slot: id'],
            ['a line break in a slot', 'workflows-create.enable', { id: 'wf_1\nwf_2' }, 'invalid_slot: id'],
            ['an overlong slot value', 'workflows-create.enable', { id: 'x'.repeat(65) }, 'invalid_slot: id'],
        ])('drops %s into errors', async (_case, key, args, reason) => {
            const result = await call([{ key, args }])
            expect(result).toEqual({ actions: [], errors: [{ key, reason }] })
        })

        it('keeps the first of two picks with the same key, so every button names one action', async () => {
            const result = await call([
                { key: 'workflows-create.enable', args: { id: 'wf_1' } },
                { key: 'workflows-create.enable', args: { id: 'wf_2' } },
            ])
            expect(result.actions.map((action) => action.message)).toEqual(['Enable workflow wf_1.'])
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'duplicate_action' }])
        })

        it('drops a run action whose target is not in the caller catalog', async () => {
            const without = new Set(['workflows-create', 'suggest-actions'])
            const result = await call([{ key: 'workflows-create.enable', args: { id: 'wf_1' } }], without)
            expect(result.actions).toEqual([])
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'run_target_unavailable' }])
        })

        it('drops every action of a tool the caller cannot see', async () => {
            const result = await call([{ key: 'workflows-create.test-send' }], new Set(['suggest-actions']))
            expect(result.errors).toEqual([{ key: 'workflows-create.test-send', reason: 'unknown_action' }])
        })

        it.each([
            ['a UUID', '0190f5a2-7c3e-7d1a-9b2f-3c4d5e6f7a8b'],
            ['a number', 42],
        ])('renders %s as a slot value', async (_case, id) => {
            const result = await call([{ key: 'workflows-create.enable', args: { id } }])
            expect(result.actions[0]!.message).toBe(`Enable workflow ${id}.`)
        })

        it('treats every run target as unavailable when no catalog is bound', async () => {
            const result = await createSuggestActionsTool().handler(context, {
                actions: [{ key: 'workflows-create.enable', args: { id: 'wf_1' } }],
            })
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'run_target_unavailable' }])
        })
    })
})
