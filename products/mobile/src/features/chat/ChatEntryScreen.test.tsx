import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import type { ReactElement } from 'react'

import { getChatRuntime, getConversation } from '@/api/conversations'
import { scopeKey } from '@/api/reports'
import { useDataMode } from '@/demo/demoMode'

import { ChatEntryScreen } from './ChatEntryScreen'

jest.mock('@/api/conversations', () => ({ getChatRuntime: jest.fn(), getConversation: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({
    useProjectScope: () => ({ host: 'https://app.example.com', projectId: 42 }),
}))
jest.mock('@/demo/demoMode', () => ({ useDataMode: jest.fn() }))
jest.mock('./ChatHeader', () => {
    const { Button } = require('react-native')
    return {
        ChatHeader: ({ onBack }: { onBack: () => void }): ReactElement => (
            <Button testID="chat-back" title="Back" onPress={onBack} />
        ),
    }
})
jest.mock('./ChatScreen', () => {
    const { Button, Text, View } = require('react-native')
    return {
        ChatScreen: ({ initialTaskId, onNewChat }: { initialTaskId?: string; onNewChat: () => void }): ReactElement => (
            <View testID="sandbox">
                <Text>{initialTaskId}</Text>
                <Button title="New" onPress={onNewChat} />
            </View>
        ),
    }
})
jest.mock('./classic/ClassicChatScreen', () => {
    const { Button, Text, View } = require('react-native')
    return {
        ClassicChatScreen: ({
            conversationId,
            onNewChat,
        }: {
            conversationId?: string
            onNewChat: () => void
        }): ReactElement => (
            <View testID="classic">
                <Text>{conversationId}</Text>
                <Button title="New" onPress={onNewChat} />
            </View>
        ),
    }
})

function open(
    props: Partial<React.ComponentProps<typeof ChatEntryScreen>> = {},
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
): void {
    render(
        <QueryClientProvider client={client}>
            <ChatEntryScreen
                source={{ entry: 'chats_empty', origin: null }}
                autoFocus={false}
                onBack={() => undefined}
                {...props}
            />
        </QueryClientProvider>
    )
}

describe('mobile AI runtime selection', () => {
    beforeEach(() => {
        jest.resetAllMocks()
        jest.mocked(useDataMode).mockReturnValue('live')
    })

    test.each(['langgraph', 'sandbox'] as const)('uses the web access decision for a new %s chat', async (runtime) => {
        jest.mocked(getChatRuntime).mockResolvedValue(runtime)
        open()
        await waitFor(() => expect(screen.getByTestId(runtime === 'sandbox' ? 'sandbox' : 'classic')).toBeTruthy())
    })

    test('a new chat rechecks access after a flag change', async () => {
        jest.mocked(getChatRuntime).mockResolvedValueOnce('langgraph').mockResolvedValueOnce('sandbox')
        open()
        await screen.findByTestId('classic')
        fireEvent.press(screen.getByText('New'))
        await screen.findByTestId('sandbox')
        expect(getChatRuntime).toHaveBeenCalledTimes(2)
    })

    test('waits for fresh access when a previous chat cached AI 2.0', async () => {
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        client.setQueryData(
            ['chat-runtime', ...scopeKey({ host: 'https://app.example.com', projectId: 42 }), 0],
            'sandbox'
        )
        let resolve!: (runtime: 'langgraph') => void
        jest.mocked(getChatRuntime).mockReturnValue(
            new Promise((done) => {
                resolve = done
            })
        )
        open({}, client)
        expect(screen.queryByTestId('sandbox')).toBeNull()
        await act(async () => resolve('langgraph'))
        await screen.findByTestId('classic')
    })

    test('an existing classic conversation keeps its engine even when AI 2.0 is enabled', async () => {
        jest.mocked(getChatRuntime).mockResolvedValue('sandbox')
        jest.mocked(getConversation).mockResolvedValue({ agent_runtime: 'langgraph' } as Awaited<
            ReturnType<typeof getConversation>
        >)
        open({ conversationId: 'conversation-1' })
        await screen.findByTestId('classic')
        expect(getChatRuntime).not.toHaveBeenCalled()
    })

    test('report chats and existing tasks keep their task path without requiring AI 2.0 access', () => {
        open({ initialReportId: 'report-1' })
        expect(screen.getByTestId('sandbox')).toBeTruthy()
        expect(getChatRuntime).not.toHaveBeenCalled()
    })

    test('an incomplete sandbox conversation never opens in the classic runtime', async () => {
        jest.mocked(getConversation).mockResolvedValue({ agent_runtime: 'sandbox', task: null } as Awaited<
            ReturnType<typeof getConversation>
        >)
        open({ conversationId: 'conversation-1' })
        await screen.findByText('This chat is not ready yet')
        expect(screen.queryByTestId('classic')).toBeNull()
        expect(screen.getByTestId('chat-back')).toBeTruthy()
    })

    test('demo mode does not request live access or conversation history', () => {
        jest.mocked(useDataMode).mockReturnValue('demo')
        open({ conversationId: 'demo-conversation' })
        expect(screen.getByTestId('sandbox')).toBeTruthy()
        expect(getChatRuntime).not.toHaveBeenCalled()
        expect(getConversation).not.toHaveBeenCalled()
    })

    test('falls back to classic when the access lookup fails', async () => {
        jest.mocked(getChatRuntime).mockRejectedValue(new Error('Offline'))
        open()
        await act(async () => undefined)
        await screen.findByTestId('classic')
    })
})
