import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react-native'
import type { ReactElement } from 'react'

import { getConversation } from '@/api/conversations'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { ChatEntryScreen } from './ChatEntryScreen'

jest.mock('@/api/conversations', () => ({ getConversation: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: jest.fn() }))
jest.mock('@/demo/demoMode', () => ({ ...jest.requireActual('@/demo/demoMode'), useDataMode: jest.fn() }))
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

function open(props: Partial<React.ComponentProps<typeof ChatEntryScreen>> = {}): void {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
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
        jest.clearAllMocks()
        jest.mocked(getConversation).mockReset()
        jest.mocked(useDataMode).mockReturnValue('live')
        jest.mocked(useProjectScope).mockReturnValue({ host: 'https://us.posthog.com', projectId: 42 })
    })

    test.each([
        ['https://us.posthog.com', 2, 'sandbox'],
        ['https://us.posthog.com', 42, 'classic'],
        ['https://eu.posthog.com', 2, 'classic'],
        ['https://example.com', 2, 'classic'],
        ['http://localhost:8010', 2, 'classic'],
    ])('selects %s project %s as %s', (host, projectId, runtime) => {
        jest.mocked(useProjectScope).mockReturnValue({ host, projectId })
        open()
        expect(screen.getByTestId(runtime)).toBeTruthy()
        expect(getConversation).not.toHaveBeenCalled()
    })

    test('a new offline chat opens without waiting for a network lookup', () => {
        onlineManager.setOnline(false)
        try {
            open()
            expect(screen.getByTestId('classic')).toBeTruthy()
            expect(getConversation).not.toHaveBeenCalled()
        } finally {
            onlineManager.setOnline(true)
        }
    })

    test('waits for the selected project before showing a new chat', () => {
        jest.mocked(useProjectScope).mockReturnValue(null)
        open()
        expect(screen.getByLabelText('Loading chat')).toBeTruthy()
        expect(screen.queryByTestId('sandbox')).toBeNull()
        expect(screen.queryByTestId('classic')).toBeNull()
    })

    test('an existing classic conversation stays classic in the agent project', async () => {
        jest.mocked(useProjectScope).mockReturnValue({ host: 'https://us.posthog.com', projectId: 2 })
        jest.mocked(getConversation).mockResolvedValue({ agent_runtime: 'langgraph' } as Awaited<
            ReturnType<typeof getConversation>
        >)
        open({ conversationId: 'conversation-1' })
        await screen.findByTestId('classic')
    })

    test('an existing sandbox conversation opens its task outside the agent project', async () => {
        jest.mocked(getConversation).mockResolvedValue({ agent_runtime: 'sandbox', task: { id: 'task-1' } } as Awaited<
            ReturnType<typeof getConversation>
        >)
        open({ conversationId: 'conversation-1' })
        await screen.findByText('task-1')
        expect(screen.getByTestId('sandbox')).toBeTruthy()
    })

    test('starting a new chat from a task uses the current project rule', () => {
        open({ initialTaskId: 'task-1' })
        expect(screen.getByText('task-1')).toBeTruthy()
        fireEvent.press(screen.getByText('New'))
        expect(screen.getByTestId('classic')).toBeTruthy()
    })

    test('report chats keep their task path outside the agent project', () => {
        open({ initialReportId: 'report-1' })
        expect(screen.getByTestId('sandbox')).toBeTruthy()
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

    test('a new demo chat resets its task without requesting conversation history', () => {
        jest.mocked(useDataMode).mockReturnValue('demo')
        open({ initialTaskId: 'demo-task' })
        expect(screen.getByText('demo-task')).toBeTruthy()
        fireEvent.press(screen.getByText('New'))
        expect(screen.queryByText('demo-task')).toBeNull()
        expect(screen.getByTestId('sandbox')).toBeTruthy()
        expect(getConversation).not.toHaveBeenCalled()
    })
})
