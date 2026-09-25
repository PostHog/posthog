import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/core'
import type { Context } from '@/tools/types'

/**
 * Both project tools accept the same four spellings of `id`, and each one holds
 * a separate `param_overrides` block in definitions/core.yaml, so the tools can
 * drift apart.
 *
 * These drive the generated handlers, because the schema snapshots record what
 * an agent is told rather than what the boundary accepts, and the two can
 * disagree. A spelling the description offers is not covered until a call that
 * uses it reaches the right project.
 */
describe('project id or @current', () => {
    const ACTIVE_PROJECT = '42'
    const NAMED_PROJECT = 7

    function mockContext(request: ReturnType<typeof vi.fn>): Context {
        return {
            api: { request },
            stateManager: { getOrgID: async () => 'org-1', getProjectId: async () => ACTIVE_PROJECT },
        } as unknown as Context
    }

    // `expected` is the whole request, so a case also fails if `id` reaches the body.
    const TOOLS = [
        {
            tool: 'project-get',
            settings: {},
            expected: (path: string) => ({ method: 'GET', path }),
        },
        {
            tool: 'project-settings-update',
            settings: { session_recording_opt_in: true },
            expected: (path: string) => ({
                method: 'PATCH',
                path,
                body: { session_recording_opt_in: true },
            }),
        },
    ]

    describe.each(TOOLS)('$tool', ({ tool, settings, expected }) => {
        async function callWith(params: Record<string, unknown>): Promise<ReturnType<typeof vi.fn>> {
            const request = vi.fn().mockResolvedValue({ id: NAMED_PROJECT })
            const generated = GENERATED_TOOLS[tool]!()

            await generated.handler(mockContext(request), generated.schema.parse({ ...params, ...settings }))

            return request
        }

        it.each([
            { spelling: 'omitted', params: {} },
            { spelling: '@current', params: { id: '@current' } },
        ])('targets the active project when id is $spelling', async ({ params }) => {
            const request = await callWith(params)

            expect(request).toHaveBeenCalledWith(expected(`/api/organizations/org-1/projects/${ACTIVE_PROJECT}/`))
        })

        it.each([
            { spelling: 'a number', params: { id: NAMED_PROJECT } },
            { spelling: 'a stringified number', params: { id: String(NAMED_PROJECT) } },
        ])('targets the named project when id is $spelling', async ({ params }) => {
            const request = await callWith(params)

            expect(request).toHaveBeenCalledWith(expected(`/api/organizations/org-1/projects/${NAMED_PROJECT}/`))
        })
    })
})
