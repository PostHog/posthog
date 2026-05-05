import { describe, expect, it, vi } from 'vitest'

import { submitFeedbackHandler } from '@/tools/feedback/submit'
import type { Context } from '@/tools/types'

function createContext(requestMock: ReturnType<typeof vi.fn>, trackEventMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock } as any,
        cache: {} as any,
        env: {} as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        sessionManager: {} as any,
        mcp: {
            sessionUuid: 'session-uuid',
            clientName: 'Claude Code',
            clientVersion: '1.2.3',
            protocolVersion: '2025-03-26',
            transport: 'streamable-http',
        },
        getDistinctId: vi.fn().mockResolvedValue('distinct-id'),
        trackEvent: trackEventMock,
    }
}

const feedbackParams = {
    summary: 'query tool schema was confusing',
    sentiment: 'mixed' as const,
    category: 'tool_input_schema' as const,
    task_completed: true,
    tools_used: ['read-data-schema', 'execute-sql'],
    friction_points: 'The query parameter shape was hard to infer.',
    suggested_improvement: 'Add a concrete filters example.',
    user_request: 'Analyze activation events',
    details: 'The task eventually succeeded.',
}

describe('submitFeedbackHandler', () => {
    it.each([
        {
            name: 'persists feedback to mcp_analytics and keeps analytics capture',
            requestResult: { id: 'submission-id' },
            expectedPersisted: true,
        },
        {
            name: 'returns received when persistence fails',
            requestError: new Error('permission denied'),
            expectedPersisted: false,
        },
    ])('$name', async ({ requestResult, requestError, expectedPersisted }) => {
        const requestMock = requestError
            ? vi.fn().mockRejectedValue(requestError)
            : vi.fn().mockResolvedValue(requestResult)
        const trackEventMock = vi.fn().mockResolvedValue(undefined)
        const context = createContext(requestMock, trackEventMock)

        const result = await submitFeedbackHandler(context, feedbackParams)

        expect(result).toEqual(
            expect.objectContaining({
                received: true,
                persisted: expectedPersisted,
                summary: feedbackParams.summary,
            })
        )

        if (expectedPersisted) {
            expect(requestMock).toHaveBeenCalledWith({
                method: 'POST',
                path: '/api/environments/42/mcp_analytics/feedback/',
                body: {
                    goal: 'Analyze activation events',
                    feedback: expect.stringContaining('Summary: query tool schema was confusing'),
                    category: 'usability',
                    attempted_tool: 'execute-sql',
                    mcp_client_name: 'Claude Code',
                    mcp_client_version: '1.2.3',
                    mcp_protocol_version: '2025-03-26',
                    mcp_transport: 'streamable-http',
                    mcp_session_id: 'session-uuid',
                },
            })
        }
        expect(trackEventMock).toHaveBeenCalledWith(
            'mcp feedback submitted',
            expect.objectContaining({
                feedback_persisted: expectedPersisted,
                feedback_mcp_session_id: 'session-uuid',
                feedback_mcp_client_name: 'Claude Code',
            })
        )
    })
})
