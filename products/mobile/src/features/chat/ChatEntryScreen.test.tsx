import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react-native'
import type { ReactElement } from 'react'

import { getConversation } from '@/api/conversations'
import { fetchOrganization, type OrganizationApi } from '@/api/users'
import { useAuthStore } from '@/auth/authStore'
import { useDataMode } from '@/demo/demoMode'
import { aiConsentKey, useAiConsentStore, waitForAiConsent } from './aiConsentStore'
import { ChatEntryScreen } from './ChatEntryScreen'

jest.mock('@/api/conversations', () => ({ getConversation: jest.fn() }))
jest.mock('@/api/users', () => ({ fetchOrganization: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({
    useProjectScope: () => ({ host: 'https://app.example.com', projectId: 42 }),
}))
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

const organization: OrganizationApi = {
    id: 'org-1',
    name: 'Example',
    teams: [{ id: 42, name: 'Project' }],
    is_ai_data_processing_approved: true,
}

describe('mobile AI runtime selection', () => {
    beforeEach(async () => {
        jest.clearAllMocks()
        jest.mocked(fetchOrganization).mockReset()
        jest.mocked(getConversation).mockReset()
        await waitForAiConsent()
        jest.mocked(useDataMode).mockReturnValue('live')
        useAuthStore.setState({
            status: 'signed_in',
            signedIn: true,
            host: 'https://app.example.com',
            projectId: 42,
            user: { id: 1, uuid: 'person-1', distinctId: 'person-1', email: 'person@example.com', name: 'Person' },
            organizations: [{ id: 'org-1', name: 'Example', posthogAiAccess: true }],
            projects: [{ id: 42, name: 'Project', organizationId: 'org-1', organizationName: 'Example' }],
        })
        useAiConsentStore.getState().accept(aiConsentKey('https://app.example.com', 'person-1'))
        jest.mocked(fetchOrganization).mockResolvedValue(organization)
    })

    test.each([true, false, undefined])('uses organization access for a new chat (%s)', async (enabled) => {
        jest.mocked(fetchOrganization).mockResolvedValue({ ...organization, posthog_ai_access: enabled })
        open()
        await screen.findByTestId(enabled === true ? 'sandbox' : 'classic')
        expect(fetchOrganization).toHaveBeenCalledTimes(1)
    })

    test('a new chat rechecks access after a flag change', async () => {
        jest.mocked(fetchOrganization)
            .mockResolvedValueOnce({ ...organization, posthog_ai_access: false })
            .mockResolvedValueOnce({ ...organization, posthog_ai_access: true })
        open()
        await screen.findByTestId('classic')
        fireEvent.press(screen.getByText('New'))
        await screen.findByTestId('sandbox')
        expect(fetchOrganization).toHaveBeenCalledTimes(2)
    })

    test('waits for fresh access instead of using cached organization access', async () => {
        let resolve!: (value: OrganizationApi) => void
        jest.mocked(fetchOrganization).mockReturnValue(
            new Promise((done) => {
                resolve = done
            })
        )
        open()
        expect(screen.queryByTestId('sandbox')).toBeNull()
        await act(async () => resolve({ ...organization, posthog_ai_access: false }))
        await screen.findByTestId('classic')
    })

    test('an existing classic conversation keeps its engine even when AI 2.0 is enabled', async () => {
        jest.mocked(fetchOrganization).mockResolvedValue({ ...organization, posthog_ai_access: true })
        jest.mocked(getConversation).mockResolvedValue({ agent_runtime: 'langgraph' } as Awaited<
            ReturnType<typeof getConversation>
        >)
        open({ conversationId: 'conversation-1' })
        await screen.findByTestId('classic')
    })

    test('report chats keep their task path without requiring AI 2.0 access', async () => {
        open({ initialReportId: 'report-1' })
        expect(screen.getByTestId('sandbox')).toBeTruthy()
        await act(async () => undefined)
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

    test('demo mode does not request organization access or conversation history', () => {
        jest.mocked(useDataMode).mockReturnValue('demo')
        open({ conversationId: 'demo-conversation' })
        expect(screen.getByTestId('sandbox')).toBeTruthy()
        expect(fetchOrganization).not.toHaveBeenCalled()
        expect(getConversation).not.toHaveBeenCalled()
    })

    test('falls back to classic when the organization lookup fails', async () => {
        jest.mocked(fetchOrganization).mockRejectedValue(new Error('Offline'))
        open()
        await screen.findByTestId('classic')
    })
})
