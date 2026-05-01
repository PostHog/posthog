import { describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/analytics'
import feedback from '@/tools/feedback/feedback'
import type { Context } from '@/tools/types'

const captureMock = vi.fn()

vi.mock('@/lib/analytics', async () => {
    const actual = await vi.importActual<typeof import('@/lib/analytics')>('@/lib/analytics')
    return {
        ...actual,
        getPostHogClient: () => ({ capture: captureMock }),
    }
})

function createMockContext(analyticsContext: Record<string, string> = {}): Context {
    return {
        api: {} as any,
        stateManager: {
            getAnalyticsContext: vi.fn().mockResolvedValue(analyticsContext),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'user-distinct-id',
    }
}

describe('feedback tool', () => {
    it('captures a feedback event with the message and acknowledges the user', async () => {
        captureMock.mockClear()
        const tool = feedback()
        const context = createMockContext({
            organizationId: 'org-1',
            projectId: '42',
            projectUuid: 'project-uuid',
            projectName: 'My Project',
        })

        const result = await tool.handler(context, {
            feedback: 'The query-run tool returned an unhelpful error',
            category: 'bug',
            severity: 'high',
            tool_name: 'query-run',
        })

        expect(captureMock).toHaveBeenCalledTimes(1)
        const captured = captureMock.mock.calls[0]![0]
        expect(captured.distinctId).toBe('user-distinct-id')
        expect(captured.event).toBe(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED)
        expect(captured.groups).toEqual({ organization: 'org-1', project: 'project-uuid' })
        expect(captured.properties).toMatchObject({
            feedback: 'The query-run tool returned an unhelpful error',
            category: 'bug',
            severity: 'high',
            tool_name: 'query-run',
            organization_id: 'org-1',
            project_id: '42',
            project_uuid: 'project-uuid',
            project_name: 'My Project',
        })
        expect(result.content[0]!.text).toContain('Thanks')
    })

    it('omits optional properties when not provided', async () => {
        captureMock.mockClear()
        const tool = feedback()
        const context = createMockContext()

        await tool.handler(context, { feedback: 'Looks great so far!' })

        const captured = captureMock.mock.calls[0]![0]
        expect(captured.properties).toEqual({ feedback: 'Looks great so far!' })
        expect(captured.groups).toBeUndefined()
    })

    it('still acknowledges feedback when analytics throws', async () => {
        captureMock.mockClear()
        captureMock.mockImplementationOnce(() => {
            throw new Error('boom')
        })
        const tool = feedback()
        const context = createMockContext()

        const result = await tool.handler(context, { feedback: 'Anything works' })

        expect(result.content[0]!.text).toContain('Thanks')
    })
})
