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

type FeedbackParams = Parameters<ReturnType<typeof feedback>['handler']>[1]

describe('feedback tool', () => {
    const captureCases: Array<{
        name: string
        analyticsContext: Record<string, string>
        params: FeedbackParams
        expectedGroups: Record<string, string> | undefined
        expectedProperties: Record<string, unknown>
        forbiddenProperties?: string[]
    }> = [
        {
            name: 'agent-observed friction with full metadata',
            analyticsContext: {
                organizationId: 'org-1',
                projectId: '42',
                projectUuid: 'project-uuid',
                projectName: 'My Project',
            },
            params: {
                feedback: 'The query-run tool returned an unhelpful error',
                source: 'agent_observed',
                posthog_area: 'MCP',
                category: 'bug',
                severity: 'high',
                tool_name: 'query-run',
            },
            expectedGroups: { organization: 'org-1', project: 'project-uuid' },
            expectedProperties: {
                feedback: 'The query-run tool returned an unhelpful error',
                source: 'agent_observed',
                posthog_area: 'MCP',
                category: 'bug',
                severity: 'high',
                tool_name: 'query-run',
                organization_id: 'org-1',
                project_id: '42',
                project_uuid: 'project-uuid',
                project_name: 'My Project',
            },
        },
        {
            name: 'user-initiated feedback about a PostHog product area',
            analyticsContext: {},
            params: {
                feedback: 'Would love a way to filter session replays by mobile OS version',
                source: 'user_initiated',
                posthog_area: 'session replay',
                category: 'missing_feature',
            },
            expectedGroups: undefined,
            expectedProperties: {
                feedback: 'Would love a way to filter session replays by mobile OS version',
                source: 'user_initiated',
                posthog_area: 'session replay',
                category: 'missing_feature',
            },
            forbiddenProperties: ['tool_name', 'skill_name'],
        },
        {
            name: 'feedback with only the required message',
            analyticsContext: {},
            params: { feedback: 'Looks great so far!' },
            expectedGroups: undefined,
            expectedProperties: { feedback: 'Looks great so far!' },
            forbiddenProperties: ['source', 'posthog_area', 'category', 'severity', 'tool_name', 'skill_name'],
        },
    ]

    it.each(captureCases)(
        'captures $name',
        async ({ analyticsContext, params, expectedGroups, expectedProperties, forbiddenProperties }) => {
            captureMock.mockClear()
            const tool = feedback()
            const context = createMockContext(analyticsContext)

            const result = await tool.handler(context, params)

            expect(captureMock).toHaveBeenCalledTimes(1)
            const captured = captureMock.mock.calls[0]![0]
            expect(captured.distinctId).toBe('user-distinct-id')
            expect(captured.event).toBe(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED)
            expect(captured.groups).toEqual(expectedGroups)
            expect(captured.properties).toMatchObject(expectedProperties)
            for (const key of forbiddenProperties ?? []) {
                expect(captured.properties).not.toHaveProperty(key)
            }
            expect(result.content[0]!.text).toContain('Thanks')
        }
    )

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
