import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS as AGENT_PLATFORM_TOOLS } from '@/tools/generated/agent_platform'
import type { Context } from '@/tools/types'

// The three agent-platform "runtime" MCP tools (agent-applications-invoke / agent-applications-send /
// agent-applications-listen) are the caller-facing bridge into a running agent session.
// These assert the generated handlers issue the exact HTTP call the Django
// viewset expects — method, project-scoped path, and body/query shape.

function createMockContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({})
    const context = {
        api: { request } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
    return { context, request }
}

describe('agent-applications-invoke', () => {
    it('POSTs to the app invoke endpoint with {message}', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-invoke']!()

        await tool.handler(context, { id: 'app-123', message: 'kick it off' })

        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/agent_applications/app-123/invoke/',
            body: { message: 'kick it off' },
        })
    })

    it('includes external_key in the body when provided', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-invoke']!()

        await tool.handler(context, { id: 'app-123', message: 'hi', external_key: 'ext-abc' })

        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/agent_applications/app-123/invoke/',
            body: { message: 'hi', external_key: 'ext-abc' },
        })
    })

    it('omits external_key from the body when not provided', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-invoke']!()

        await tool.handler(context, { id: 'app-123', message: 'hi' })

        const body = request.mock.calls[0]![0].body
        expect(body).not.toHaveProperty('external_key')
    })
})

describe('agent-applications-send', () => {
    it('POSTs to the app send endpoint with {session_id, message}', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-send']!()

        await tool.handler(context, { id: 'app-123', session_id: 'sess-9', message: 'more input' })

        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/agent_applications/app-123/send/',
            body: { session_id: 'sess-9', message: 'more input' },
        })
    })
})

describe('agent-applications-listen', () => {
    it('GETs the app listen endpoint with {cursor, max_chars, session_id} query', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-listen']!()

        await tool.handler(context, {
            id: 'app-123',
            session_id: 'sess-9',
            cursor: 3,
            max_chars: 1000,
        })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/agent_applications/app-123/listen/',
            query: {
                cursor: 3,
                max_chars: 1000,
                session_id: 'sess-9',
            },
        })
    })

    it('is a GET (never mutates) — no request body', async () => {
        const { context, request } = createMockContext()
        const tool = AGENT_PLATFORM_TOOLS['agent-applications-listen']!()

        await tool.handler(context, { id: 'app-123', session_id: 'sess-9' })

        const call = request.mock.calls[0]![0]
        expect(call.method).toBe('GET')
        expect(call).not.toHaveProperty('body')
    })
})
