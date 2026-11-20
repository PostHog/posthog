import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { buildCliCatalog } from '@/cli/catalog/build'
import { createApiToolLibrary } from '@/cli/library'
import { getToolsFromContext } from '@/tools'
import { createExecTool } from '@/tools/exec'
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
    const id = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'

    // Both routes run from their public entry point over real HTTP, so a dispatch that picks a handler
    // without the note, or a catalog entry the CLI drops, fails here.
    async function throughRoute(
        route: 'the MCP server' | 'the CLI',
        name: string,
        input: Record<string, unknown>,
        response: unknown
    ): Promise<{ result: any; requests: { method: string; path: string; body: unknown }[]; baseUrl: string }> {
        const requests: { method: string; path: string; body: unknown }[] = []
        const server = createServer((request, reply) => {
            let raw = ''
            request.on('data', (chunk) => (raw += chunk))
            request.on('end', () => {
                const path = new URL(request.url!, 'http://localhost').pathname
                reply.setHeader('Content-Type', 'application/json')
                if (!path.startsWith('/api/projects/42/hog_flows/')) {
                    reply.statusCode = 404
                    reply.end(JSON.stringify({ detail: 'Not found.' }))
                    return
                }
                requests.push({ method: request.method!, path, body: raw ? JSON.parse(raw) : undefined })
                reply.end(JSON.stringify(response))
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
        try {
            if (route === 'the CLI') {
                const called = await createApiToolLibrary({ catalog: buildCliCatalog(null) }).call(
                    name,
                    input,
                    { apiKey: 'phx_test', host: baseUrl, projectId: '42', clientName: 'hog', clientVersion: '0.0.0' },
                    true
                )
                if (!called.ok) {
                    throw new Error(called.error.message)
                }
                return { result: called.value, requests, baseUrl }
            }
            const context = {
                ...createMockContext(vi.fn()),
                api: new ApiClient({ apiToken: 'phx_test', baseUrl }),
                stateManager: {
                    getProjectId: async () => '42',
                    getAiConsentGiven: async () => true,
                    getApiKey: async () => ({ scopes: ['hog_flow:read', 'hog_flow:write'] }),
                    getUser: async () => ({ is_staff: false }),
                },
            } as unknown as Context
            const exec = createExecTool(await getToolsFromContext(context), context, '', '', undefined)
            const output = await exec.handler(context, { command: `call --json ${name} ${JSON.stringify(input)}` })
            return { result: typeof output === 'string' ? JSON.parse(output) : output, requests, baseUrl }
        } finally {
            await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
        }
    }

    const routes = ['the MCP server', 'the CLI'] as const
    const throughEachRoute = (rows: any[][]): any[][] =>
        rows.flatMap(([name, ...rest]) => routes.map((route) => [name, route, ...rest]))

    it.each(
        throughEachRoute([
            [
                'a draft workflow on the test sender',
                undefined,
                testSenderLive,
                true,
                '/project/42/workflows/wf-1/workflow',
            ],
            ['a broadcast', 'broadcasts', [], false, '/project/42/broadcasts/wf-1'],
            ['a workflow on its own sender', undefined, [], false, '/project/42/workflows/wf-1/workflow'],
            ['a workflow with malformed warnings', undefined, [null], false, '/project/42/workflows/wf-1/workflow'],
            [
                'a workflow whose warning has no message',
                undefined,
                [{ code: 'test_sender_live', message: ' ' }],
                false,
                '/project/42/workflows/wf-1/workflow',
            ],
        ])
    )(
        'relays the test sender warning only when it enables %s, through %s',
        async (_name, route, origin, warnings, relays, path) => {
            const { result, requests, baseUrl } = await throughRoute(
                route,
                'workflows-enable',
                { id },
                { ...workflow(), origin_product: origin, warnings }
            )

            expect(requests).toEqual([
                { method: 'PATCH', path: `/api/projects/42/hog_flows/${id}/`, body: { status: 'active' } },
            ])
            expect(result._agentNote?.includes('test_sender_live') ?? false).toBe(relays)
            expect(result.warnings).toEqual(warnings)
            expect(result._posthogUrl).toBe(`${baseUrl}${path}`)
        }
    )

    it.each(
        throughEachRoute([
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
            [
                'a preview that shows the live workflow',
                {},
                {
                    published: false,
                    confirm_token: 'preview-token',
                    workflow: { ...workflow(), warnings: testSenderLive },
                },
                false,
            ],
        ])
    )(
        'relays the test sender warning only for %s, through %s',
        async (_name, route, confirmation, response, relays) => {
            const { result, requests } = await throughRoute(
                route,
                'workflows-publish',
                { id, ...confirmation },
                response
            )

            expect(requests.map((request) => `${request.method} ${request.path}`)).toEqual([
                `POST /api/projects/42/hog_flows/${id}/publish/`,
            ])
            expect(result._agentNote?.includes('test_sender_live') ?? false).toBe(relays)
            expect(result.workflow?.warnings).toEqual((response as any).workflow?.warnings)
        }
    )
})
