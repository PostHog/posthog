import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState } from 'react-native'

import { fetchSessionObservations, requestSessionSummary } from '@/api/replayVision'
import { fetchOrganization, type OrganizationApi } from '@/api/users'
import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { cancelAiApproval, checkAiApproval, useAiApprovalStore } from '@/features/ai/aiApproval'
import { aiConsentKey, useAiConsentStore } from '@/features/chat/aiConsentStore'

import { useOrgAiStatus, useSessionSummaryFlow } from './hooks'
import { SummaryCard } from './SummaryCard'

jest.mock('@/api/users', () => ({ fetchOrganization: jest.fn() }))
jest.mock('@/api/replayVision', () => ({
    ...jest.requireActual<typeof import('@/api/replayVision')>('@/api/replayVision'),
    fetchSessionObservations: jest.fn(),
    requestSessionSummary: jest.fn(),
}))
jest.mock('expo-router', () => ({
    useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]),
}))

const HOST = 'https://app.example.com'
const ORG: OrganizationApi = {
    id: 'org-1',
    name: 'Example',
    teams: [{ id: 7, name: 'Project' }],
    is_ai_data_processing_approved: false,
    membership_level: 1,
}

function Summary(): ReactElement {
    const flow = useSessionSummaryFlow('session-1')
    return (
        <SummaryCard
            card={flow.card}
            aiStatus={useOrgAiStatus()}
            pending={flow.pending}
            onSummarize={flow.summarize}
            onCheckAgain={flow.checkAgain}
        />
    )
}

test('a blocked replay opens shared approval without scanning; a fresh approval then permits the scan', async () => {
    AppState.currentState = 'active'
    useDemoMode.setState({ enabled: false })
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        method: null,
        host: HOST,
        projectId: 7,
        user: { uuid: 'person-1', distinctId: 'distinct-1', email: 'person@example.com', name: 'Person' },
        organizations: [{ id: ORG.id, name: ORG.name, aiDataProcessingApproved: false, membershipLevel: 1 }],
        projects: [{ id: 7, name: 'Project', organizationId: ORG.id, organizationName: ORG.name }],
    })
    useAiConsentStore.getState().accept(aiConsentKey(HOST, 'person-1'))
    jest.mocked(fetchOrganization).mockResolvedValue(ORG)
    jest.mocked(fetchSessionObservations).mockResolvedValue({ results: [] })
    jest.mocked(requestSessionSummary).mockResolvedValue('started')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { unmount } = render(<Summary />, { wrapper })
    try {
        await waitFor(() => expect(screen.getByTestId('session-summary-ai-access')).toBeTruthy())
        fireEvent.press(screen.getByTestId('session-summary-ai-access'))
        await waitFor(() =>
            expect(useAiApprovalStore.getState().request?.access).toMatchObject({
                kind: 'org_blocked',
                canApprove: false,
                settingsUrl: null,
            })
        )
        expect(requestSessionSummary).not.toHaveBeenCalled()
        jest.mocked(fetchOrganization).mockResolvedValue({ ...ORG, is_ai_data_processing_approved: true })
        await act(async () => {
            await checkAiApproval()
        })
        await waitFor(() => expect(requestSessionSummary).toHaveBeenCalledWith('session-1', expect.anything()))
    } finally {
        unmount()
        cancelAiApproval()
        client.clear()
        useAiConsentStore.getState().clear()
    }
})
