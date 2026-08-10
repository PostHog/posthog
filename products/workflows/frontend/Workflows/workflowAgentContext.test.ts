import { HogFunctionTemplateType } from '~/types'

import type { HogFlow } from './hogflows/types'
import { redactWorkflowSecretInputs } from './workflowAgentContext'

const templatesById = {
    'template-webhook-dest': {
        id: 'template-webhook-dest',
        inputs_schema: [
            { key: 'api_key', type: 'string', secret: true },
            { key: 'url', type: 'string' },
        ],
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

    it('redacts entries carrying the saved secret marker even without a known template', () => {
        const workflow = workflowWith({
            actions: [
                {
                    id: 'a1',
                    type: 'function',
                    config: {
                        template_id: 'template-unknown',
                        inputs: { token: { value: 'leaked-token', secret: true } },
                    },
                },
            ] as unknown as HogFlow['actions'],
        })

        const inputs = (redactWorkflowSecretInputs(workflow, templatesById).actions[0] as any).config.inputs
        expect(inputs.token.value).toBe('[secret]')
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
