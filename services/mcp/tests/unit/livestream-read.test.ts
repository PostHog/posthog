import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import livestreamRead, { collectLivestreamEvents, getLivestreamHost } from '@/tools/livestream/read'
import type { Context } from '@/tools/types'

type ProjectsGet = (args: { projectId: string }) => Promise<{
    success: boolean
    data?: { live_events_token: string | null }
    error?: Error
}>

function createMockContext(opts: { projectId?: string; baseUrl?: string; projectsGet: ProjectsGet }): Context {
    return {
        api: {
            baseUrl: opts.baseUrl ?? 'https://us.posthog.com',
            projects: () => ({ get: opts.projectsGet }),
        } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue(opts.projectId ?? '42'),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function encodeSseChunk(text: string): Uint8Array {
    return new TextEncoder().encode(text)
}

function sseStreamFromEvents(events: object[]): ReadableStream<Uint8Array> {
    return new ReadableStream({
        start(controller) {
            for (const event of events) {
                controller.enqueue(encodeSseChunk(`data: ${JSON.stringify(event)}\n\n`))
            }
            controller.close()
        },
    })
}

describe('getLivestreamHost', () => {
    it.each([
        ['https://us.posthog.com', 'https://live.us.posthog.com'],
        ['https://eu.posthog.com', 'https://live.eu.posthog.com'],
        ['https://app.dev.posthog.dev', 'https://live.dev.posthog.dev'],
        ['http://localhost:8010', 'http://localhost:8666'],
        ['http://127.0.0.1:8010', 'http://localhost:8666'],
    ])('maps %s to %s', (input, expected) => {
        expect(getLivestreamHost(input)).toBe(expected)
    })

    it('rejects unknown self-hosted base URLs', () => {
        expect(() => getLivestreamHost('https://posthog.acme.corp')).toThrow(/livestream is not reachable/i)
    })
})

describe('collectLivestreamEvents', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('collects events until limit is reached and aborts the stream', async () => {
        const events = [
            { event: 'a', uuid: '1' },
            { event: 'b', uuid: '2' },
            { event: 'c', uuid: '3' },
            { event: 'd', uuid: '4' },
        ]
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(sseStreamFromEvents(events), {
                status: 200,
                headers: { 'Content-Type': 'text/event-stream' },
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const { events: collected } = await collectLivestreamEvents({
            url: 'https://live.us.posthog.com/events',
            token: 'jwt-token',
            limit: 2,
            waitMs: 5000,
        })

        expect(collected.map((e) => e.event)).toEqual(['a', 'b'])
        const [, fetchOpts] = mockFetch.mock.calls[0]!
        expect(fetchOpts.headers.Authorization).toBe('Bearer jwt-token')
        expect(fetchOpts.headers.Accept).toBe('text/event-stream')
    })

    it('returns no events when the stream produces nothing within the wait window', async () => {
        const stream = new ReadableStream<Uint8Array>({
            start(controller) {
                // Never enqueues; only closes after a delay shorter than wait_ms.
                setTimeout(() => controller.close(), 30)
            },
        })
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { status: 200 })))

        const { events } = await collectLivestreamEvents({
            url: 'https://live.us.posthog.com/events',
            token: 'jwt-token',
            limit: 50,
            waitMs: 200,
        })

        expect(events).toEqual([])
    })

    it('throws a descriptive error on non-2xx responses', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(new Response('forbidden token', { status: 403, statusText: 'Forbidden' }))
        )

        await expect(
            collectLivestreamEvents({
                url: 'https://live.us.posthog.com/events',
                token: 'bad-token',
                limit: 10,
                waitMs: 1000,
            })
        ).rejects.toThrow(/403/)
    })
})

describe('livestreamRead tool', () => {
    let mockFetch: ReturnType<typeof vi.fn>

    beforeEach(() => {
        mockFetch = vi.fn().mockResolvedValue(
            new Response(sseStreamFromEvents([{ event: 'user_signed_up', uuid: 'abc' }]), {
                status: 200,
            })
        )
        vi.stubGlobal('fetch', mockFetch)
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('fetches live_events_token from the project and forwards filters as query params', async () => {
        const projectsGet = vi.fn().mockResolvedValue({
            success: true,
            data: { live_events_token: 'live-jwt' },
        })
        const tool = livestreamRead()
        const context = createMockContext({ projectsGet })

        const result = await tool.handler(context, {
            event_types: ['user_signed_up', '$pageview'],
            distinct_id: 'user-1',
            properties: { $current_url: 'https://example.com/checkout' },
            limit: 1,
            wait_seconds: 1,
        })

        expect(projectsGet).toHaveBeenCalledWith({ projectId: '42' })

        const [calledUrl, calledOpts] = mockFetch.mock.calls[0]!
        const parsed = new URL(calledUrl as string)
        expect(parsed.origin).toBe('https://live.us.posthog.com')
        expect(parsed.pathname).toBe('/events')
        expect(parsed.searchParams.get('eventType')).toBe('user_signed_up,$pageview')
        expect(parsed.searchParams.get('distinctId')).toBe('user-1')
        expect(parsed.searchParams.getAll('property')).toEqual(['$current_url=https://example.com/checkout'])
        expect((calledOpts as RequestInit).headers).toMatchObject({
            Authorization: 'Bearer live-jwt',
        })

        expect(result.livestream_host).toBe('https://live.us.posthog.com')
        expect(result.event_count).toBe(1)
        expect(result.events[0]!.event).toBe('user_signed_up')
        expect(result.notice).toBeUndefined()
    })

    it('includes a notice when no events are captured', async () => {
        vi.unstubAllGlobals()
        const stream = new ReadableStream<Uint8Array>({
            start(controller) {
                setTimeout(() => controller.close(), 20)
            },
        })
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { status: 200 })))

        const projectsGet = vi.fn().mockResolvedValue({
            success: true,
            data: { live_events_token: 'live-jwt' },
        })
        const context = createMockContext({ projectsGet })
        const result = await livestreamRead().handler(context, { wait_seconds: 1 })

        expect(result.event_count).toBe(0)
        expect(result.notice).toContain('No events were captured')
    })

    it('throws when the project has no live_events_token', async () => {
        const projectsGet = vi.fn().mockResolvedValue({
            success: true,
            data: { live_events_token: null },
        })
        const context = createMockContext({ projectsGet })

        await expect(livestreamRead().handler(context, {})).rejects.toThrow(/no live_events_token/i)
    })

    it('throws when the project lookup fails', async () => {
        const projectsGet = vi.fn().mockResolvedValue({
            success: false,
            error: new Error('Forbidden'),
        })
        const context = createMockContext({ projectsGet })

        await expect(livestreamRead().handler(context, {})).rejects.toThrow(/failed to load project/i)
    })
})
