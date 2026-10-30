import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import createEventDefinition from '@/tools/projects/createEventDefinition'
import getEventDefinition from '@/tools/projects/getEventDefinition'
import updateEventDefinition from '@/tools/projects/updateEventDefinition'
import type { Context } from '@/tools/types'

const owner = {
    id: 7,
    uuid: '0190f9a6-0000-0000-0000-000000000007',
    distinct_id: 'owner-distinct-id',
    first_name: 'Ada',
    last_name: 'Lovelace',
    email: 'ada@example.com',
    is_email_verified: true,
    hedgehog_config: null,
}

const definition = {
    id: '0190f9a6-1111-2222-3333-444444444444',
    name: 'user_signed_up',
    owner,
    description: 'Fired when a user finishes sign-up',
    tags: ['onboarding'],
    verified: true,
    hidden: false,
    created_at: '2026-01-02T03:04:05Z',
    last_seen_at: '2026-10-27T12:00:00Z',
}

function stubFetch(...responses: Response[]): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn()
    for (const response of responses) {
        fetchMock.mockResolvedValueOnce(response)
    }
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
}

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function createContext(): Context {
    return {
        api: new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' }),
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function requestBody(fetchMock: ReturnType<typeof vi.fn>, call: number): unknown {
    return JSON.parse(fetchMock.mock.calls[call]![1].body)
}

describe('event definition owner', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it.each([
        ['sets', 7],
        ['clears', null],
    ])('event-definition-update %s the owner', async (_label, ownerId) => {
        const fetchMock = stubFetch(json(definition), json({ ...definition, owner: ownerId === null ? null : owner }))
        const tool = updateEventDefinition()

        // Parse through the tool schema as the server does: before `owner` was in it, the key was stripped.
        const params = tool.schema.parse({ eventName: 'user_signed_up', data: { owner: ownerId } })
        const result = await tool.handler(createContext(), params)

        expect(fetchMock.mock.calls[1]![0]).toBe(
            `https://us.posthog.com/api/projects/17/event_definitions/${definition.id}/`
        )
        expect(requestBody(fetchMock, 1)).toEqual({ owner: ownerId })
        expect(result.url).toBe(`https://us.posthog.com/project/17/data-management/events/${definition.id}`)
    })

    it('event-definition-create sends the owner', async () => {
        const fetchMock = stubFetch(json(definition, 201))
        const tool = createEventDefinition()

        const params = tool.schema.parse({ eventName: 'user_signed_up', data: { owner: 7 } })
        await tool.handler(createContext(), params)

        expect(requestBody(fetchMock, 0)).toEqual({ name: 'user_signed_up', owner: 7 })
    })

    it.each([0, -1, 1.5, 'ada@example.com'])('rejects %s as an owner ID', (ownerId) => {
        const result = updateEventDefinition().schema.safeParse({
            eventName: 'user_signed_up',
            data: { owner: ownerId },
        })

        expect(result.success).toBe(false)
    })

    it('event-definition-get returns the owner and the seen times', async () => {
        const fetchMock = stubFetch(json(definition))
        const tool = getEventDefinition()

        const result = await tool.handler(createContext(), tool.schema.parse({ eventName: 'user_signed_up' }))

        expect(fetchMock.mock.calls[0]![0]).toBe(
            'https://us.posthog.com/api/projects/17/event_definitions/by_name/?name=user_signed_up'
        )
        expect(result).toEqual({
            found: true,
            id: definition.id,
            name: 'user_signed_up',
            description: 'Fired when a user finishes sign-up',
            owner: { id: 7, email: 'ada@example.com', first_name: 'Ada', last_name: 'Lovelace' },
            tags: ['onboarding'],
            verified: true,
            hidden: false,
            first_seen_at: '2026-01-02T03:04:05Z',
            last_seen_at: '2026-10-27T12:00:00Z',
            url: `https://us.posthog.com/project/17/data-management/events/${definition.id}`,
        })
    })

    it('event-definition-get returns a null owner when none is set', async () => {
        stubFetch(json({ ...definition, owner: null }))
        const tool = getEventDefinition()

        const result = await tool.handler(createContext(), tool.schema.parse({ eventName: 'user_signed_up' }))

        expect(result).toMatchObject({ found: true, owner: null })
    })

    it('event-definition-get reports a missing definition as data, not an error', async () => {
        stubFetch(json({ detail: "Event definition with name 'nope' not found" }, 404))
        const tool = getEventDefinition()

        const result = await tool.handler(createContext(), tool.schema.parse({ eventName: 'nope' }))

        expect(result).toMatchObject({ found: false, eventName: 'nope' })
    })

    it('event-definition-get throws on other API errors', async () => {
        stubFetch(json({ detail: 'You do not have permission to perform this action.' }, 403))
        const tool = getEventDefinition()

        await expect(tool.handler(createContext(), tool.schema.parse({ eventName: 'user_signed_up' }))).rejects.toThrow(
            'Failed to get event definition'
        )
    })
})
