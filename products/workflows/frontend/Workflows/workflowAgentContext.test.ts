import { HogFunctionTemplateType } from '~/types'

import type { HogFlow } from './hogflows/types'
import {
    EDITOR_STATE_MAX_CHARS,
    redactWorkflowSecretInputs,
    serializeWorkflowEditorState,
} from './workflowAgentContext'

const templatesById = {
    'template-webhook-dest': {
        id: 'template-webhook-dest',
        inputs_schema: [
            { key: 'api_key', type: 'string', secret: true },
            { key: 'url', type: 'string' },
        ],
    } as unknown as HogFunctionTemplateType,
    // Hidden built-in templates like template-email are returned on the authenticated mount, so the
    // loaded map contains them in practice.
    'template-email': {
        id: 'template-email',
        inputs_schema: [{ key: 'email', type: 'email' }],
    } as unknown as HogFunctionTemplateType,
}

function workflowWith(overrides: Partial<HogFlow>): HogFlow {
    return {
        id: 'flow-1',
        name: 'Test flow',
        actions: [],
        edges: [],
        ...overrides,
    } as unknown as HogFlow
}

function emailActions(value: Record<string, unknown>): HogFlow['actions'] {
    return [
        {
            id: 'e1',
            type: 'function_email',
            config: { template_id: 'template-email', inputs: { email: { value } } },
        },
    ] as unknown as HogFlow['actions']
}

describe('workflowAgentContext', () => {
    describe('redactWorkflowSecretInputs', () => {
        it('redacts a typed-but-unsaved schema-secret input on a function action, keeping non-secret values', () => {
            const workflow = workflowWith({
                actions: [
                    {
                        id: 'a1',
                        type: 'function',
                        config: {
                            template_id: 'template-webhook-dest',
                            inputs: {
                                api_key: { value: 'sk-live-1234567890', bytecode: ['_H', 'sk-live-1234567890'] },
                                url: { value: 'https://example.com/hook' },
                            },
                        },
                    },
                ] as unknown as HogFlow['actions'],
            })

            const redacted = redactWorkflowSecretInputs(workflow, templatesById)
            const inputs = (redacted.actions[0] as any).config.inputs

            expect(inputs.api_key.value).toBe('[secret]')
            expect(inputs.api_key.bytecode).toBeUndefined()
            expect(inputs.url.value).toBe('https://example.com/hook')
            expect(JSON.stringify(redacted)).not.toContain('sk-live-1234567890')
        })

        // Templates load asynchronously (and the fetch can fail), so a secret typed into a field whose
        // template schema isn't available yet must not leak: without the schema every value is redacted.
        it('redacts every input value when the template schema is unavailable (fail closed)', () => {
            const workflow = workflowWith({
                actions: [
                    {
                        id: 'a1',
                        type: 'function',
                        config: {
                            template_id: 'template-not-loaded',
                            inputs: {
                                token: { value: 'leaked-token', secret: true },
                                url: {
                                    value: 'https://example.com/hook',
                                    bytecode: ['_H', 'https://example.com/hook'],
                                },
                            },
                        },
                    },
                ] as unknown as HogFlow['actions'],
            })

            const inputs = (redactWorkflowSecretInputs(workflow, {}).actions[0] as any).config.inputs
            expect(inputs.token.value).toBe('[redacted]')
            expect(inputs.url.value).toBe('[redacted]')
            expect(inputs.url.bytecode).toBeUndefined()
        })

        it('redacts webhook trigger action inputs via the trigger template schema', () => {
            const workflow = workflowWith({
                actions: [
                    {
                        id: 't1',
                        type: 'trigger',
                        config: {
                            type: 'webhook',
                            template_id: 'template-webhook-dest',
                            inputs: { api_key: { value: 'sk-live-1234567890' } },
                        },
                    },
                ] as unknown as HogFlow['actions'],
            })

            const inputs = (redactWorkflowSecretInputs(workflow, templatesById).actions[0] as any).config.inputs
            expect(inputs.api_key.value).toBe('[secret]')
        })

        it('redacts mapping inputs via the mapping inline schema', () => {
            const workflow = workflowWith({
                actions: [
                    {
                        id: 'a1',
                        type: 'function',
                        config: {
                            template_id: 'template-unknown',
                            inputs: {},
                            mappings: [
                                {
                                    name: 'm1',
                                    inputs_schema: [{ key: 'password', type: 'string', secret: true }],
                                    inputs: { password: { value: 'hunter2' } },
                                },
                            ],
                        },
                    },
                ] as unknown as HogFlow['actions'],
            })

            const mapping = (redactWorkflowSecretInputs(workflow, templatesById).actions[0] as any).config.mappings[0]
            expect(mapping.inputs.password.value).toBe('[secret]')
        })

        it('does not mutate the input workflow', () => {
            const workflow = workflowWith({
                actions: [
                    {
                        id: 'a1',
                        type: 'function',
                        config: {
                            template_id: 'template-webhook-dest',
                            inputs: { api_key: { value: 'sk-live-1234567890' } },
                        },
                    },
                ] as unknown as HogFlow['actions'],
            })

            redactWorkflowSecretInputs(workflow, templatesById)
            expect((workflow.actions[0] as any).config.inputs.api_key.value).toBe('sk-live-1234567890')
        })
    })

    describe('serializeWorkflowEditorState', () => {
        // The rendered html is re-derived server-side from the design on every save, so shipping it
        // alongside the design would double (or worse) the payload attached to every message.
        it('drops the rendered html from email steps with a design, keeping it on html-only steps', () => {
            const withDesign = serializeWorkflowEditorState(
                workflowWith({ actions: emailActions({ design: { rows: ['r1'] }, html: '<html>rendered</html>' }) }),
                templatesById
            )
            expect(withDesign).not.toContain('rendered')
            expect(withDesign).toContain('r1')
            expect(withDesign).not.toContain('elided for size')

            const htmlOnly = serializeWorkflowEditorState(
                workflowWith({ actions: emailActions({ html: '<html>only body</html>' }) }),
                templatesById
            )
            expect(htmlOnly).toContain('only body')
        })

        it('elides email designs once the serialized state exceeds the cap, keeping the JSON parseable', () => {
            const serialized = serializeWorkflowEditorState(
                workflowWith({
                    actions: emailActions({ design: { blocks: 'x'.repeat(EDITOR_STATE_MAX_CHARS) }, subject: 'Hi' }),
                }),
                templatesById
            )

            expect(serialized.length).toBeLessThan(EDITOR_STATE_MAX_CHARS)
            const emailValue = JSON.parse(serialized).actions[0].config.inputs.email.value
            expect(emailValue.design).toContain('elided for size')
            expect(emailValue.subject).toBe('Hi')
        })
    })
})
