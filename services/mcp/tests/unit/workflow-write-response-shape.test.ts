import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'
import { workflowsEnable } from '@/tools/workflows/lifecycle'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const emailStep = (): Record<string, unknown> => ({
    id: 'email_1',
    type: 'function_email',
    name: 'Day 1: welcome',
    config: {
        type: 'function_email',
        template_id: 'template-email',
        inputs: { email: { value: { html: 'x'.repeat(20000), design: { body: { rows: [] } } } } },
    },
})

const workflow = (): Record<string, unknown> => ({
    id: 'wf-1',
    name: 'Onboarding',
    status: 'active',
    version: 28,
    actions: [emailStep()],
    edges: [{ from: 'trigger', to: 'email_1' }],
    draft: { actions: [emailStep()], edges: [] },
})

function expectStepWithoutInputs(step: any): void {
    expect(step).toMatchObject({ id: 'email_1', type: 'function_email', name: 'Day 1: welcome' })
    expect(step.config).not.toHaveProperty('inputs')
    // broadcastLinkHooks reads config.type to offer the broadcast conversion, so the omit
    // has to take `config.inputs` and not `config`.
    expect(step.config).toMatchObject({ type: 'function_email' })
}

describe('workflow write response shape', () => {
    it('drops step inputs from a graph patch response', async () => {
        const request = vi.fn().mockResolvedValue(workflow())

        const result: any = await GENERATED_TOOLS['workflows-patch-graph']!().handler(createMockContext(request), {
            id: 'wf-1',
            operations: [{ op: 'remove_action', id: 'email_2' }],
        } as any)

        expectStepWithoutInputs(result.actions[0])
        expectStepWithoutInputs(result.draft.actions[0])
    })

    it('drops step inputs from an enable response', async () => {
        const request = vi.fn().mockResolvedValue(workflow())

        const result: any = await workflowsEnable().handler(createMockContext(request), { id: 'wf-1' } as any)

        expect(result.status).toBe('active')
        expectStepWithoutInputs(result.actions[0])
        expectStepWithoutInputs(result.draft.actions[0])
    })

    it('drops step inputs from the workflow nested in a publish response', async () => {
        // An unmatched omit path is dropped with no error, which would put the whole graph back on the wire.
        const request = vi.fn().mockResolvedValue({ published: true, impact: null, workflow: workflow() })

        const result: any = await GENERATED_TOOLS['workflows-publish']!().handler(createMockContext(request), {
            id: 'wf-1',
            confirm: true,
        } as any)

        expect(result.published).toBe(true)
        expectStepWithoutInputs(result.workflow.actions[0])
        expectStepWithoutInputs(result.workflow.draft.actions[0])
    })
})
