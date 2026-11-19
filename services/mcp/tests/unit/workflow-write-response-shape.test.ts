import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

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

        const result: any = await GENERATED_TOOLS['workflows-enable']!().handler(createMockContext(request), {
            id: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
        } as any)

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

    const testSenderLive = [{ code: 'test_sender_live', message: 'Set up your sending domain.' }]

    it.each([
        ['a draft workflow on the test sender', undefined, testSenderLive, true, '/project/42/workflows/wf-1/workflow'],
        ['a broadcast on the test sender', 'broadcasts', testSenderLive, true, '/project/42/broadcasts/wf-1'],
        ['a workflow on its own sender', undefined, [], false, '/project/42/workflows/wf-1/workflow'],
        ['a workflow with malformed warnings', undefined, [null], false, '/project/42/workflows/wf-1/workflow'],
        [
            'a workflow whose warning has no message',
            undefined,
            [{ code: 'test_sender_live', message: ' ' }],
            false,
            '/project/42/workflows/wf-1/workflow',
        ],
    ])('relays the test sender warning only when it enables %s', async (_name, origin, warnings, relays, path) => {
        const request = vi.fn().mockResolvedValue({ ...workflow(), origin_product: origin, warnings })

        const result: any = await GENERATED_TOOLS['workflows-enable']!().handler(createMockContext(request), {
            id: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
        } as any)

        expect(request.mock.calls[0]?.[0]).toMatchObject({
            method: 'PATCH',
            path: '/api/projects/42/hog_flows/0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b/',
            body: { status: 'active' },
        })
        expect(result._agentNote?.includes('test_sender_live') ?? false).toBe(relays)
        expect(result.warnings).toEqual(warnings)
        expect(result._posthogUrl).toBe(`https://us.posthog.com${path}`)
    })

    it.each([
        [
            'a publish onto the test sender',
            { confirm: true, confirm_token: 'preview-token' },
            { published: true, workflow: { ...workflow(), warnings: testSenderLive } },
            true,
        ],
        [
            'a publish on its own sender',
            { confirm: true, confirm_token: 'preview-token' },
            { published: true, workflow: { ...workflow(), warnings: [] } },
            false,
        ],
        ['a preview', {}, { published: false, confirm_token: 'preview-token', impact: null }, false],
    ])('relays the test sender warning only for %s', async (_name, confirmation, response, relays) => {
        const request = vi.fn().mockResolvedValue(response)

        const result: any = await GENERATED_TOOLS['workflows-publish']!().handler(createMockContext(request), {
            id: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
            ...confirmation,
        } as any)

        expect(result._agentNote?.includes('test_sender_live') ?? false).toBe(relays)
        expect(result.workflow?.warnings).toEqual((response as any).workflow?.warnings)
    })
})
