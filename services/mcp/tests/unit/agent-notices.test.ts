import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResolvedState } from '@/hono/request-state-resolver'
import { maybeInjectAgentNotice } from '@/lib/agent-notices'
import { evaluateFeatureFlags } from '@/lib/posthog/flags'

vi.mock('@/lib/posthog/flags', () => ({
    evaluateFeatureFlags: vi.fn(async () => ({})),
}))

type NoticeFixture = {
    id: string
    message: string
    feature_flag_key: string | null
    starts_at: string
    expires_at: string
    created_at: string
}

type StateFixture = {
    state: ResolvedState
    sessionCache: { get: ReturnType<typeof vi.fn>; set: ReturnType<typeof vi.fn> }
    trackEvent: ReturnType<typeof vi.fn>
    fetchNotices: ReturnType<typeof vi.fn>
}

function makeNotice(overrides: Partial<NoticeFixture> = {}): NoticeFixture {
    return {
        id: 'notice-1',
        message: 'The bug you hit was fixed.',
        feature_flag_key: null,
        starts_at: new Date(Date.now() - 3600_000).toISOString(),
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        created_at: new Date(Date.now() - 3600_000).toISOString(),
        ...overrides,
    }
}

function makeState(
    overrides: {
        enabled?: boolean
        sessionId?: string | undefined
        fetchNotices?: () => Promise<unknown>
        delivered?: string[]
    } = {}
): StateFixture {
    const sessionStore = new Map<string, unknown>()
    if (overrides.delivered) {
        sessionStore.set('agentNoticesDelivered', overrides.delivered)
    }
    const sessionCache = {
        get: vi.fn(async (k: string) => sessionStore.get(k)),
        set: vi.fn(async (k: string, v: unknown) => {
            sessionStore.set(k, v)
        }),
    }
    const trackEvent = vi.fn(async () => undefined)
    const fetchNotices = vi.fn(overrides.fetchNotices ?? (async () => [makeNotice()]))
    const state = {
        agentNoticesEnabled: overrides.enabled ?? true,
        requestContext: { mcpSessionId: 'sessionId' in overrides ? overrides.sessionId : 'session-1' },
        reqCtx: { sessionCache, getAnalyticsContextSafe: vi.fn(async () => ({ organizationId: 'org-1' })) },
        distinctId: 'user-distinct-id',
        context: {
            trackEvent,
            stateManager: { getCachedOrFetchAgentNotices: fetchNotices },
        },
    } as unknown as ResolvedState
    return { state, sessionCache, trackEvent, fetchNotices }
}

function makePayload(): { content: Array<{ type: string; text: string }>; structuredContent: { rows: number[] } } {
    return { content: [{ type: 'text', text: 'tool result' }], structuredContent: { rows: [1] } }
}

function noticeText(result: unknown): string | undefined {
    const content = (result as { content: Array<{ text: string }> }).content
    return content.find((c) => c.text.includes('<posthog-notice>'))?.text
}

describe('maybeInjectAgentNotice', () => {
    afterEach(() => {
        vi.useRealTimers()
        vi.clearAllMocks()
    })

    it('returns payload unchanged when the flag is off', async () => {
        const { state, fetchNotices } = makeState({ enabled: false })
        const payload = makePayload()

        const result = await maybeInjectAgentNotice(payload, state, 'query-trends')

        expect(result).toEqual(makePayload())
        expect(fetchNotices).not.toHaveBeenCalled()
    })

    it('returns payload unchanged when there is no MCP session id', async () => {
        const { state, fetchNotices } = makeState({ sessionId: undefined })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(result).toEqual(makePayload())
        expect(fetchNotices).not.toHaveBeenCalled()
    })

    it('returns error payloads unchanged', async () => {
        const { state, fetchNotices } = makeState()
        const payload = { ...makePayload(), isError: true }

        const result = await maybeInjectAgentNotice(payload, state, 'query-trends')

        expect(result).toEqual({ ...makePayload(), isError: true })
        expect(fetchNotices).not.toHaveBeenCalled()
    })

    it('returns non-object payloads unchanged', async () => {
        const { state } = makeState()

        expect(await maybeInjectAgentNotice('plain string', state, 'query-trends')).toBe('plain string')
        expect(await maybeInjectAgentNotice(undefined, state, 'query-trends')).toBeUndefined()
    })

    it('appends a notice block, records delivery, and tracks an event', async () => {
        const { state, sessionCache, trackEvent } = makeState()
        const payload = makePayload()

        const result = await maybeInjectAgentNotice(payload, state, 'query-trends')

        const text = noticeText(result)
        expect(text).toContain('The bug you hit was fixed.')
        expect(text).toContain('</posthog-notice>')
        expect((result as { content: unknown[] }).content).toHaveLength(2)
        expect((result as { structuredContent: unknown }).structuredContent).toEqual({ rows: [1] })
        expect(sessionCache.set).toHaveBeenCalledWith('agentNoticesDelivered', ['notice-1'])
        expect(trackEvent).toHaveBeenCalledWith('mcp agent notice delivered', {
            notice_ids: ['notice-1'],
            tool_name: 'query-trends',
        })
    })

    it('does not deliver the same notice twice in a session', async () => {
        const { state } = makeState({ delivered: ['notice-1'] })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(noticeText(result)).toBeUndefined()
    })

    it('skips notices a concurrent call delivered between the first read and the re-check', async () => {
        const { state, sessionCache } = makeState()
        sessionCache.get.mockResolvedValueOnce([]).mockResolvedValueOnce(['notice-1'])

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(noticeText(result)).toBeUndefined()
        expect(sessionCache.set).not.toHaveBeenCalled()
    })

    it('delivers a notice published mid-session alongside the dedup of earlier ones', async () => {
        const { state, sessionCache } = makeState({
            delivered: ['notice-1'],
            fetchNotices: async () => [makeNotice(), makeNotice({ id: 'notice-2', message: 'Second update.' })],
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        const text = noticeText(result)
        expect(text).toContain('Second update.')
        expect(text).not.toContain('The bug you hit was fixed.')
        expect(sessionCache.set).toHaveBeenCalledWith('agentNoticesDelivered', ['notice-1', 'notice-2'])
    })

    it('skips notices the token cache still holds past their expiry', async () => {
        const { state } = makeState({
            fetchNotices: async () => [makeNotice({ expires_at: new Date(Date.now() - 60_000).toISOString() })],
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(noticeText(result)).toBeUndefined()
    })

    it('returns payload unchanged and records nothing when the fetch throws', async () => {
        const { state, sessionCache } = makeState({
            fetchNotices: async () => {
                throw new Error('django down')
            },
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(result).toEqual(makePayload())
        expect(sessionCache.set).not.toHaveBeenCalled()
    })

    it('delivers a flag-gated notice when its flag evaluates true', async () => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'dw-release-december': true })
        const { state } = makeState({
            fetchNotices: async () => [
                makeNotice({ id: 'gated', message: 'DW December is live.', feature_flag_key: 'dw-release-december' }),
            ],
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(noticeText(result)).toContain('DW December is live.')
        expect(evaluateFeatureFlags).toHaveBeenCalledWith(['dw-release-december'], 'user-distinct-id', {
            organization: 'org-1',
        })
    })

    it('withholds a flag-gated notice when its flag is false or unevaluated', async () => {
        vi.mocked(evaluateFeatureFlags).mockResolvedValueOnce({ 'dw-release-december': false })
        const { state, sessionCache } = makeState({
            fetchNotices: async () => [makeNotice({ feature_flag_key: 'dw-release-december' })],
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(noticeText(result)).toBeUndefined()
        expect(sessionCache.set).not.toHaveBeenCalled()
    })

    it('still delivers ungated notices when flag evaluation throws', async () => {
        vi.mocked(evaluateFeatureFlags).mockRejectedValueOnce(new Error('flags down'))
        const { state, sessionCache } = makeState({
            fetchNotices: async () => [
                makeNotice({ id: 'ungated', message: 'Plain notice.' }),
                makeNotice({ id: 'gated', message: 'Gated notice.', feature_flag_key: 'dw-release-december' }),
            ],
        })

        const result = await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        const text = noticeText(result)
        expect(text).toContain('Plain notice.')
        expect(text).not.toContain('Gated notice.')
        expect(sessionCache.set).toHaveBeenCalledWith('agentNoticesDelivered', ['ungated'])
    })

    it('does not evaluate flags when no pending notice is gated', async () => {
        const { state } = makeState()

        await maybeInjectAgentNotice(makePayload(), state, 'query-trends')

        expect(evaluateFeatureFlags).not.toHaveBeenCalled()
    })

    it('gives up after the soft timeout when the fetch hangs', async () => {
        vi.useFakeTimers()
        const { state, sessionCache } = makeState({ fetchNotices: () => new Promise(() => {}) })

        const resultPromise = maybeInjectAgentNotice(makePayload(), state, 'query-trends')
        await vi.advanceTimersByTimeAsync(1500)
        const result = await resultPromise

        expect(result).toEqual(makePayload())
        expect(sessionCache.set).not.toHaveBeenCalled()
    })
})
