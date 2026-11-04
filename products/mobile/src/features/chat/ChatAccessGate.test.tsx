import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { Linking, Text } from 'react-native'

import { fetchOrganization } from '@/api/users'
import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { OverlayHost } from '@/ui/OverlayPortal'

import { aiConsentKey, useAiConsentStore } from './aiConsentStore'
import { ChatAccessGate } from './ChatAccessGate'

jest.mock('@/api/users', () => ({ fetchOrganization: jest.fn() }))

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

const HOST = 'https://us.posthog.com'
const USER_UUID = 'user-uuid-1'

function signIn(approved: boolean, membershipLevel: number | null = 8): void {
    jest.mocked(fetchOrganization).mockResolvedValue({
        id: 'org-1',
        name: 'Hedgebox',
        teams: [{ id: 7, name: 'Hedgebox' }],
        is_ai_data_processing_approved: approved,
        membership_level: membershipLevel,
    })
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        host: HOST,
        user: { id: 1, uuid: USER_UUID, distinctId: 'distinct-1', email: 'max@example.com', name: 'Max' },
        organizations: [{ id: 'org-1', name: 'Hedgebox', aiDataProcessingApproved: approved, membershipLevel }],
        projects: [{ id: 7, name: 'Hedgebox', organizationId: 'org-1', organizationName: 'Hedgebox' }],
        projectId: 7,
    })
}

async function renderGate(onDecline: () => void = jest.fn()): Promise<void> {
    render(
        <ChatAccessGate onDecline={onDecline}>
            <Text testID="composer">Composer</Text>
        </ChatAccessGate>,
        { wrapper: OverlayHost }
    )
    // Lets the persisted demo and consent stores finish loading.
    await act(async () => undefined)
}

beforeEach(() => {
    // The sheet unmounts on a timer after it closes.
    jest.useFakeTimers()
    useDemoMode.setState({ enabled: false })
    useAiConsentStore.getState().clear()
})
afterEach(() => {
    act(() => jest.runOnlyPendingTimers())
    jest.useRealTimers()
})

describe('ChatAccessGate', () => {
    test.each<[string, { approved: boolean; consented: boolean; demo: boolean }, string, string[]]>([
        [
            'an organization that has not approved AI shows the notice instead of the composer',
            { approved: false, consented: true, demo: false },
            'chat-ai-org-notice',
            ['composer', 'chat-ai-consent'],
        ],
        [
            'a person who already agreed gets the composer directly',
            { approved: true, consented: true, demo: false },
            'composer',
            ['chat-ai-consent', 'chat-ai-org-notice'],
        ],
        [
            'demo mode sends nothing, so it skips both gates',
            { approved: false, consented: false, demo: true },
            'composer',
            ['chat-ai-consent', 'chat-ai-org-notice'],
        ],
    ])('%s', async (_name, { approved, consented, demo }, shown, hidden) => {
        signIn(approved)
        useDemoMode.setState({ enabled: demo })
        if (consented) {
            useAiConsentStore.getState().accept(aiConsentKey(HOST, USER_UUID))
        }

        await renderGate()

        expect(screen.getByTestId(shown)).toBeTruthy()
        for (const testID of hidden) {
            expect(screen.queryByTestId(testID)).toBeNull()
        }
    })

    test('the org notice opens the AI setting of the chat project on the web', async () => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        signIn(false)

        await renderGate()
        fireEvent.press(screen.getByTestId('chat-ai-org-settings'))

        expect(open).toHaveBeenCalledWith(`${HOST}/project/7/settings/organization-details#organization-ai-consent`)
        expect(screen.getByTestId('chat-ai-org-notice')).toHaveTextContent(/PostHog AI is off for Hedgebox/)
    })

    test.each([1, null])(
        'members and unknown roles get admin guidance without a settings link (%s)',
        async (membership) => {
            signIn(false, membership)
            await renderGate()
            expect(screen.queryByTestId('chat-ai-org-settings')).toBeNull()
            expect(screen.getByTestId('chat-ai-org-notice')).toHaveTextContent(/Ask an admin or owner/)
        }
    )

    test('Continue stores consent and reveals the composer', async () => {
        signIn(true)

        await renderGate()
        expect(screen.getByTestId('chat-ai-consent')).toBeTruthy()
        expect(screen.queryByTestId('composer')).toBeNull()
        fireEvent.press(screen.getByTestId('chat-ai-consent-continue'))

        expect(screen.getByTestId('composer')).toBeTruthy()
        expect(useAiConsentStore.getState().accepted[aiConsentKey(HOST, USER_UUID)]).toBe(true)
    })

    test('Not now closes the chat without storing consent', async () => {
        const onDecline = jest.fn()
        signIn(true)

        await renderGate(onDecline)
        fireEvent.press(screen.getByTestId('chat-ai-consent-not-now'))

        expect(onDecline).toHaveBeenCalledTimes(1)
        expect(screen.queryByTestId('composer')).toBeNull()
        expect(useAiConsentStore.getState().accepted).toEqual({})
    })
})
