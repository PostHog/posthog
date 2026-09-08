import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

interface RequestArgs {
    method: string
    path: string
    body?: Record<string, unknown>
}

function createMockContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({ id: 'report-123' })
    const context = {
        api: {
            request,
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
        },
    } as unknown as Context

    return { context, request }
}

const claimTool = GENERATED_TOOLS['inbox-reports-claim']!()

describe('inbox-reports-claim handler', () => {
    it('accepts report_id and posts claim fields to the report action', async () => {
        const { context, request } = createMockContext()
        const params = claimTool.schema.parse({
            report_id: 'report-123',
            pr_url: 'https://github.com/PostHog/posthog/pull/123',
            release: false,
        })

        await claimTool.handler(context, params)

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call).toEqual({
            method: 'POST',
            path: '/api/projects/42/signals/reports/report-123/claim/',
            body: {
                pr_url: 'https://github.com/PostHog/posthog/pull/123',
                release: false,
            },
        })
    })

    it('sends release without inventing a pull request field', async () => {
        const { context, request } = createMockContext()
        const params = claimTool.schema.parse({ report_id: 'report-123', release: true })

        await claimTool.handler(context, params)

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.body).toEqual({ release: true })
    })
})
