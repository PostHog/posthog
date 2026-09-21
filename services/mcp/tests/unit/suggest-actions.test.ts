import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import { chatActionToolsToExclude, type ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { ChatActionSchema } from '@/tools/chatActions'
import {
    bindSuggestActionsCatalog,
    createSuggestActionsTool,
    type SuggestActionsResult,
} from '@/tools/posthogAiTools/suggestActions'
import { getToolDefinition, getToolDefinitions, ToolDefinitionSchema } from '@/tools/toolDefinitions'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { ToolConfigSchema } from '../../scripts/yaml-config-schema'

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

        it('declares the two workflow actions on workflows-create', () => {
            expect(getToolDefinition('workflows-create').actions).toEqual([
                {
                    key: 'enable',
                    label: 'Enable the workflow',
                    kind: 'run',
                    tool: 'workflows-enable',
                    message: 'Enable workflow {id}.',
                },
                {
                    key: 'test-send',
                    label: 'Fire a real send to your address',
                    kind: 'insert',
                    message: 'Send a real test of this workflow to ',
                },
            ])
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
            expect(rendered).toContain('do not repeat the offered actions in prose')
            expect(rendered).toContain('After `workflows-create`:')
            expect(rendered).toContain('- `workflows-create.enable` (run, slots: id): Enable the workflow')
            expect(rendered).toContain('- `workflows-create.test-send` (insert): Fire a real send to your address')
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
            expect(rendered).toContain('- `workflows-create.test-send` (insert)')
            expect(rendered).not.toContain('workflows-create.enable')
        })
    })

    describe('tool exposure', () => {
        it.each([
            ['posthog_ai', []],
            ['posthog-code', ['suggest-actions']],
            [undefined, ['suggest-actions']],
        ])('consumer %s excludes %j', (consumer, excluded) => {
            expect(chatActionToolsToExclude(new MCPClientProfile({ consumer }))).toEqual(excluded)
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
        const call = (
            actions: { key: string; args?: Record<string, string | number | boolean> }[],
            names = catalog
        ): Promise<SuggestActionsResult> => createSuggestActionsTool(names).handler(context, { actions })

        it('renders the picked actions in input order and never leaks tool or args', async () => {
            const result = await call([
                { key: 'workflows-create.test-send' },
                { key: 'workflows-create.enable', args: { id: 'wf_123' } },
            ])
            expect(result).toEqual({
                actions: [
                    {
                        key: 'workflows-create.test-send',
                        label: 'Fire a real send to your address',
                        kind: 'insert',
                        message: 'Send a real test of this workflow to ',
                    },
                    {
                        key: 'workflows-create.enable',
                        label: 'Enable the workflow',
                        kind: 'run',
                        message: 'Enable workflow wf_123.',
                    },
                ],
                errors: [],
            })
        })

        it.each([
            ['an unknown tool', 'nope.enable', {}, 'unknown_action'],
            ['an unknown key on a known tool', 'workflows-create.delete', {}, 'unknown_action'],
            ['a key without a tool prefix', 'enable', {}, 'unknown_action'],
            ['a missing slot', 'workflows-create.enable', {}, 'missing_slot: id'],
            ['a blank slot value', 'workflows-create.enable', { id: '   ' }, 'missing_slot: id'],
        ])('drops %s into errors', async (_case, key, args, reason) => {
            const result = await call([{ key, args }])
            expect(result).toEqual({ actions: [], errors: [{ key, reason }] })
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

        it('does not expand a slot marker carried inside a slot value', async () => {
            const result = await call([{ key: 'workflows-create.enable', args: { id: '{id}' } }])
            expect(result.actions[0]!.message).toBe('Enable workflow {id}.')
        })

        // The agent controls args and the rendered message lands in the composer as-is, so a value
        // must not smuggle in line breaks or unbounded text.
        it('flattens whitespace and caps the length of a slot value', async () => {
            const result = await call([{ key: 'workflows-create.enable', args: { id: `a\n\n b${'x'.repeat(500)}` } }])
            const message = result.actions[0]!.message
            expect(message).not.toContain('\n')
            expect(message.startsWith('Enable workflow a b')).toBe(true)
            expect(message.length).toBeLessThanOrEqual('Enable workflow .'.length + 200)
        })

        it('binds the catalog onto the suggest-actions entry of a tool list and leaves the rest alone', async () => {
            const other = {
                name: 'workflows-create',
                handler: async () => 'unchanged',
            } as unknown as Tool<ZodObjectAny>
            const unbound = createSuggestActionsTool() as unknown as Tool<ZodObjectAny>
            const [boundOther, boundSuggest] = bindSuggestActionsCatalog([other, unbound])
            expect(boundOther).toBe(other)
            const result = (await boundSuggest!.handler(context, {
                actions: [{ key: 'workflows-create.test-send' }],
            })) as { actions: unknown[] }
            expect(result.actions).toHaveLength(1)
        })

        it('treats every run target as unavailable when no catalog is bound', async () => {
            const result = await createSuggestActionsTool().handler(context, {
                actions: [{ key: 'workflows-create.enable', args: { id: 'wf_1' } }],
            })
            expect(result.errors).toEqual([{ key: 'workflows-create.enable', reason: 'run_target_unavailable' }])
        })
    })
})
