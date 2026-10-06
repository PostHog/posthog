import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'
import { ReactNode } from 'react'

import { initKeaTests } from '~/test/init'

import { SendTestEmailModal } from './SendTestEmailModal'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({
        setModalOpen: jest.fn(),
        setRecipientEmail: jest.fn(),
        setSenderIntegrationId: jest.fn(),
        sendTestEmail: jest.fn(),
    }),
}))

jest.mock('lib/lemon-ui/LemonModal', () => ({
    LemonModal: ({ children, footer }: { children: ReactNode; footer: ReactNode }) => (
        <>
            {children}
            {footer}
        </>
    ),
}))

describe('SendTestEmailModal', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    const mockValues = (overrides: Record<string, unknown>): void => {
        jest.mocked(useValues).mockReturnValue({
            recipientEmail: '',
            recipientSuggestions: [],
            sandboxEmailSenderEnabled: true,
            recipientOutsideOrganization: false,
            senderIntegrationId: null,
            sandboxEmailSender: null,
            isSandboxSenderSelected: false,
            emailIntegrations: [],
            emailIntegrationsLoading: false,
            membersLoading: false,
            sendDisabledReason: undefined,
            testSendResult: null,
            testSendResultLoading: false,
            testSendSkipMessage: null,
            ...overrides,
        })
    }

    it.each([
        [true, false],
        [false, true],
    ])(
        'shows skeleton rows instead of the empty state while the member list loads (loading=%s, empty state=%s)',
        (membersLoading, emptyStateShown) => {
            mockValues({ membersLoading })
            render(<SendTestEmailModal id="new" isOpen />)

            fireEvent.focus(screen.getByPlaceholderText('you@example.com'))

            expect(document.querySelector('.LemonSkeleton') !== null).toBe(!emptyStateShown)
            expect(screen.queryByText('Type an email address and press Enter') !== null).toBe(emptyStateShown)
        }
    )
})
