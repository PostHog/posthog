import { fetch as streamingFetch } from 'expo/fetch'

import { setAuthProvider } from './client'
import { type ChatAgentMode, fetchConversation, openConversationStream } from './conversations'

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }))

const streamMock = streamingFetch as unknown as jest.Mock<Promise<Response>, [string, RequestInit]>

describe('conversations api', () => {
    beforeEach(() => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2 }),
            refreshAccessToken: async () => null,
        })
        streamMock.mockReset()
        streamMock.mockResolvedValue(new Response('', { status: 200 }))
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test.each<[string, ChatAgentMode | null, Record<string, unknown>]>([
        ['leaves agent_mode out for Auto', null, {}],
        ['sends the chosen agent_mode', 'sql', { agent_mode: 'sql' }],
    ])('%s', async (_name, agentMode, extra) => {
        await openConversationStream(
            { conversationId: 'c-1', traceId: 't-1', content: 'Hi', agentMode },
            new AbortController().signal
        )

        const [url, init] = streamMock.mock.calls[0] as [string, RequestInit]
        expect(url).toBe('https://app.example.com/api/projects/2/conversations/')
        expect(JSON.parse(String(init.body))).toEqual({ conversation: 'c-1', trace_id: 't-1', content: 'Hi', ...extra })
    })

    test.each<[unknown, ChatAgentMode | null]>([
        ['session_replay', 'session_replay'],
        ['user_interview', 'product_analytics'],
        ['customer_analytics', null],
        [undefined, null],
    ])('reads stored agent_mode %p as %p', async (stored, expected) => {
        globalThis.fetch = jest.fn(
            async () =>
                new Response(
                    JSON.stringify({ id: 'c-1', status: 'idle', title: 'Chat', messages: [], agent_mode: stored }),
                    {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    }
                )
        ) as unknown as typeof fetch

        await expect(fetchConversation('c-1')).resolves.toMatchObject({ agent_mode: expected })
    })
})
